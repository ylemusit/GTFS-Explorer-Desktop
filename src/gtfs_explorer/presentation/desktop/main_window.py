"""Shell Qt que refleja el estado global sin duplicar reglas de acciones."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.application.commands.create_project import CreateProject
from gtfs_explorer.application.commands.import_feed import ImportFeed, ImportFeedResult
from gtfs_explorer.application.commands.open_project import OpenedProject, OpenProject
from gtfs_explorer.application.jobs.import_job import ImportProgress
from gtfs_explorer.application.queries.feed_overview import FeedOverviewQueries
from gtfs_explorer.application.queries.geometry import GeometryQueries
from gtfs_explorer.application.queries.map_layers import MapLayerPayload, map_layers_for_trip
from gtfs_explorer.application.queries.raw import RawInspectorQueries
from gtfs_explorer.application.queries.routes import RouteExplorerQueries
from gtfs_explorer.application.queries.stops import StopInspectorQueries
from gtfs_explorer.application.queries.subset import MiniGtfsSubsetQueries
from gtfs_explorer.application.queries.timetable import TimetableMatrix, TimetableQueries
from gtfs_explorer.application.queries.validation import ValidationQueries
from gtfs_explorer.application.ui_state import UiAction, UiMode, UiState
from gtfs_explorer.domain.ports import PagedResult, PageRequest
from gtfs_explorer.domain.project import JobState, ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.raw import RawPage, RawQuery
from gtfs_explorer.domain.routes import (
    DirectionSummary,
    RouteSummary,
    ServiceSummary,
    TimelineStop,
    TripSummary,
)
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import ScheduleSpec, load_schedule_spec
from gtfs_explorer.domain.stops import StopInspection
from gtfs_explorer.domain.subset import CoreSubset, SubsetSelection
from gtfs_explorer.domain.validation import ValidationIssueFilter, ValidationIssueSummary
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.exporting.csv_exporter import (
    CsvExporter,
    CsvExportMode,
    CsvExportOptions,
)
from gtfs_explorer.infrastructure.exporting.geojson_exporter import (
    GeoJsonExporter,
    GeoJsonExportSelection,
)
from gtfs_explorer.infrastructure.exporting.gtfs_subset import (
    MiniGtfsSubsetExporter,
    MiniGtfsTable,
)
from gtfs_explorer.infrastructure.exporting.json_exporter import (
    JsonBundleExporter,
    JsonExportSelection,
)
from gtfs_explorer.infrastructure.exporting.validation_report import (
    ReportFormat,
    ValidationReportExporter,
    ValidationReportFilter,
)
from gtfs_explorer.infrastructure.filesystem.paths import application_resource_path
from gtfs_explorer.infrastructure.logging import (
    export_diagnostics,
    preview_diagnostics,
    safe_context,
)
from gtfs_explorer.presentation.desktop.exporter import (
    ExportAssistantWidget,
    ExportFormat,
    ExportRequest,
    ExportResult,
)
from gtfs_explorer.presentation.desktop.help import HelpCatalog, HelpDialog
from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.presentation.desktop.import_adapter import ImportJobAdapter
from gtfs_explorer.presentation.desktop.overview.widget import FeedOverviewWidget
from gtfs_explorer.presentation.desktop.raw.widget import RawInspectorWidget
from gtfs_explorer.presentation.desktop.routes.widget import RouteExplorerWidget
from gtfs_explorer.presentation.desktop.validation.widget import ValidationWidget

_SPECIFICATION_PATH = application_resource_path("schemas/gtfs_schedule/2026-04-27/spec.json")


class MainWindow(QMainWindow):
    """Ventana base, sin inventar datos de proyecto ni de transporte."""

    def __init__(
        self,
        *,
        cancel_active_job: Callable[[], None] | None = None,
        import_command_factory: Callable[
            [InputSource, Callable[[ImportProgress], None]], ImportFeed
        ]
        | None = None,
        logger: logging.Logger | None = None,
        logs_directory: Path | None = None,
        debug: bool = False,
    ) -> None:
        super().__init__()
        self._state = UiState()
        self._cancel_active_job = cancel_active_job
        self._opened_project: OpenedProject | None = None
        self._import_command_factory = import_command_factory
        self._logger = logger or logging.getLogger("gtfs_explorer")
        self._logs_directory = logs_directory
        self._debug = debug
        self._error_sequence = 0
        self._import_adapter = ImportJobAdapter(self)
        self._import_adapter.progress.connect(self._show_import_progress)
        self._import_adapter.finished.connect(self._import_finished)
        self._import_adapter.failed.connect(self._import_failed)
        self.setWindowTitle("GTFS Explorer Desktop")
        self.resize(1024, 680)
        self.setAcceptDrops(True)
        self._build_layout()
        self._build_actions()
        self._help_catalog = HelpCatalog.load_default()
        self._apply_state()

    @property
    def ui_state(self) -> UiState:
        """Estado actual expuesto para los adaptadores de aplicación y las pruebas."""
        return self._state

    def project_opened(self, *, recovery_required: bool = False) -> None:
        self._state = self._state.project_opened(recovery_required=recovery_required)
        self._apply_state()

    def project_closed(self) -> None:
        self._state = self._state.project_closed()
        self._apply_state()

    def job_started(self) -> None:
        self._state = self._state.job_started()
        self._apply_state()

    def job_finished(self, *, recovery_required: bool = False) -> None:
        self._state = self._state.job_finished(recovery_required=recovery_required)
        self._apply_state()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - nombre impuesto por Qt
        if self._state.allows(UiAction.CANCEL_JOB):
            self._state = self._state.cancellation_requested()
            self._apply_state()
            if self._cancel_active_job is not None:
                self._cancel_active_job()
            event.ignore()
            return
        if self._state.mode is UiMode.JOB_CANCELLING:
            event.ignore()
            return
        self._close_project()
        event.accept()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - nombre impuesto por Qt
        mime_data = event.mimeData()
        urls = mime_data.urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - nombre impuesto por Qt
        url = event.mimeData().urls()[0]
        path = Path(url.toLocalFile())
        try:
            self._request_import(self._source_from_path(path))
        except ValueError as error:
            self._show_error(str(error))
            return
        event.acceptProposedAction()

    def _build_layout(self) -> None:
        navigation = QListWidget()
        navigation.setObjectName("navigation")
        navigation.addItems(
            [
                t("navigation.project"),
                t("navigation.explore"),
                t("navigation.validation"),
                t("navigation.export"),
            ]
        )
        navigation.setAccessibleName(t("navigation.title"))
        navigation.setEnabled(False)
        navigation.currentRowChanged.connect(self._show_section)
        self._navigation = navigation
        dock = QDockWidget(t("navigation.title"), self)
        dock.setObjectName("navigationDock")
        dock.setWidget(navigation)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        central = QWidget()
        layout = QVBoxLayout(central)
        self._content_label = QLabel()
        self._content_label.setWordWrap(True)
        self._content_label.setAccessibleName("Estado actual")
        layout.addWidget(self._content_label)
        self._overview = FeedOverviewWidget(self._show_validation)
        layout.addWidget(self._overview, 1)
        self._explorer = RouteExplorerWidget(
            self._query_routes,
            self._query_services,
            self._query_directions,
            self._query_trips,
            self._query_timeline,
            self._query_stop,
            self._query_timetable,
            self._query_map_layers,
        )
        self._raw_inspector = RawInspectorWidget(self._query_raw)
        self._validation = ValidationWidget(
            self._query_validation,
            navigate_to_raw=self._show_validation_raw,
            show_help=self._show_validation_help,
            export_report=self._export_validation_report,
        )
        self._exporter = ExportAssistantWidget(executor=self._export_feed)
        self._explore_tabs = QTabWidget()
        self._explore_tabs.setObjectName("explorerTabs")
        self._explore_tabs.addTab(self._explorer, t("explore.routes"))
        self._explore_tabs.addTab(self._raw_inspector, t("explore.raw"))
        self._explore_tabs.setAccessibleName(t("navigation.explore"))
        self._explore_tabs.hide()
        layout.addWidget(self._explore_tabs, 1)
        self._validation.hide()
        layout.addWidget(self._validation, 1)
        self._exporter.hide()
        layout.addWidget(self._exporter, 1)
        self.setCentralWidget(central)

        settings = QDockWidget(t("action.settings"), self)
        settings.setObjectName("settingsDock")
        settings_widget = QWidget(settings)
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.addWidget(QLabel(t("settings.map_label")))
        choose_map = QPushButton(t("settings.choose_map"), settings_widget)
        choose_map.setAccessibleDescription("Abre el selector de un paquete de mapa local.")
        choose_map.setObjectName("selectMapPackage")
        choose_map.clicked.connect(self._select_map_package)
        settings_layout.addWidget(choose_map)
        self._map_package_status = QLabel(t("settings.map_empty"))
        self._map_package_status.setWordWrap(True)
        settings_layout.addWidget(self._map_package_status)
        settings_layout.addStretch()
        settings.setWidget(settings_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, settings)
        settings.hide()
        self._settings_dock = settings
        self._status_label = QLabel()
        self._status_label.setAccessibleName("Estado de la aplicación")
        self.statusBar().addWidget(self._status_label)
        self._progress_bar = QProgressBar()
        self._progress_bar.setAccessibleName("Progreso de importación")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.hide()
        self.statusBar().addPermanentWidget(self._progress_bar)

    def _build_actions(self) -> None:
        self._actions = {
            UiAction.NEW_PROJECT: QAction(t("action.new_project"), self),
            UiAction.OPEN_PROJECT: QAction(t("action.open_project"), self),
            UiAction.CLOSE_PROJECT: QAction(t("action.close_project"), self),
            UiAction.IMPORT_FEED: QAction(t("action.import_feed"), self),
            UiAction.CANCEL_JOB: QAction(t("action.cancel_job"), self),
            UiAction.SHOW_SETTINGS: QAction(t("action.settings"), self),
        }
        self._help_action = QAction(t("action.help"), self)
        self._actions[UiAction.NEW_PROJECT].setShortcut(QKeySequence.StandardKey.New)
        self._actions[UiAction.OPEN_PROJECT].setShortcut(QKeySequence.StandardKey.Open)
        self._actions[UiAction.CLOSE_PROJECT].setShortcut(QKeySequence.StandardKey.Close)
        self._actions[UiAction.IMPORT_FEED].setShortcut(QKeySequence("Ctrl+I"))
        self._actions[UiAction.CANCEL_JOB].setShortcut(QKeySequence.StandardKey.Cancel)
        self._actions[UiAction.SHOW_SETTINGS].setShortcut(QKeySequence("Ctrl+,"))
        self._help_action.setShortcut(QKeySequence.StandardKey.HelpContents)
        self._actions[UiAction.NEW_PROJECT].triggered.connect(self._choose_new_project)
        self._actions[UiAction.OPEN_PROJECT].triggered.connect(self._choose_project)
        self._actions[UiAction.CLOSE_PROJECT].triggered.connect(self._close_project)
        self._actions[UiAction.IMPORT_FEED].triggered.connect(self._choose_import_source)
        self._actions[UiAction.CANCEL_JOB].triggered.connect(self._request_cancellation)
        self._actions[UiAction.SHOW_SETTINGS].triggered.connect(self._settings_dock.show)
        self._help_action.triggered.connect(self._show_help)
        toolbar = QToolBar(t("toolbar.title"), self)
        toolbar.setAccessibleName(t("toolbar.title"))
        self.addToolBar(toolbar)
        for toolbar_action in self._actions.values():
            toolbar.addAction(toolbar_action)
        toolbar.addAction(self._help_action)

    def _request_cancellation(self) -> None:
        if not self._state.allows(UiAction.CANCEL_JOB):
            return
        self._state = self._state.cancellation_requested()
        self._apply_state()
        if self._cancel_active_job is not None:
            self._cancel_active_job()
        self._import_adapter.cancel()

    def _choose_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Abrir proyecto GTFS Explorer")
        if not directory:
            return
        try:
            self._close_project()
            opened = OpenProject(Path(directory)).execute()
        except Exception as error:
            self._show_error(str(error))
            return
        self._opened_project = opened
        self.project_opened(
            recovery_required=opened.descriptor.status == ProjectStatus.RECOVERY_REQUIRED
        )
        self._refresh_overview()

    def _choose_new_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Crear proyecto GTFS Explorer")
        if not directory:
            return
        try:
            self._close_project()
            opened = CreateProject(Path(directory)).execute()
        except Exception as error:
            self._show_error(str(error))
            return
        self._opened_project = opened
        self.project_opened()
        self._refresh_overview()

    def _close_project(self) -> None:
        if self._opened_project is not None:
            self._opened_project.close()
            self._opened_project = None
        self._overview.clear()
        self._raw_inspector.clear()
        self._explorer.clear()
        self._validation.clear()
        self._exporter.set_executor(None)
        if self._state.mode not in {UiMode.NO_PROJECT, UiMode.JOB_RUNNING, UiMode.JOB_CANCELLING}:
            self.project_closed()

    def _choose_import_source(self) -> None:
        choice = QMessageBox.question(
            self,
            "Fuente de importación",
            "¿Desea importar una carpeta GTFS? Seleccione No para elegir un ZIP o CSV.",
        )
        if choice is QMessageBox.StandardButton.Yes:
            selected = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta GTFS")
        else:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Seleccionar archivo GTFS",
                filter="GTFS (*.zip *.txt *.csv);;Todos los archivos (*)",
            )
        if not selected:
            return
        try:
            self._request_import(self._source_from_path(Path(selected)))
        except ValueError as error:
            self._show_error(str(error))

    def _request_import(self, source: InputSource) -> None:
        if not self._state.allows(UiAction.IMPORT_FEED):
            raise ValueError("Abra un proyecto listo antes de importar un feed.")
        confirm = QMessageBox.question(
            self,
            "Confirmar importación",
            f"Se realizará el preflight e importará '{source.path.name}'. ¿Continuar?",
        )
        if confirm is not QMessageBox.StandardButton.Yes:
            return
        self.start_import(source)

    def start_import(self, source: InputSource) -> None:
        """Inicia el trabajo desde una interacción ya confirmada de la UI."""
        if not self._state.allows(UiAction.IMPORT_FEED):
            raise RuntimeError("No se puede importar en el estado actual.")
        self.job_started()
        self._progress_bar.setValue(0)
        self._progress_bar.show()
        self._import_adapter.start(
            lambda on_progress: self._build_import_command(source, on_progress)
        )

    def _build_import_command(
        self, source: InputSource, on_progress: Callable[[ImportProgress], None]
    ) -> ImportFeed:
        if self._import_command_factory is not None:
            return self._import_command_factory(source, on_progress)
        if self._opened_project is None:
            raise RuntimeError("No hay un proyecto abierto para importar.")
        descriptor = self._opened_project.descriptor
        return ImportFeed(
            self._opened_project.database,
            ProjectMetadata(
                descriptor.project_id,
                descriptor.name,
                ProjectStatus(descriptor.status),
            ),
            source,
            load_schedule_spec(_SPECIFICATION_PATH),
            on_progress=on_progress,
        )

    @staticmethod
    def _source_from_path(path: Path) -> InputSource:
        if path.is_dir():
            return InputSource(path, InputSourceKind.DIRECTORY)
        if not path.is_file():
            raise ValueError("La fuente seleccionada no existe.")
        if path.suffix.casefold() == ".zip":
            return InputSource(path, InputSourceKind.ARCHIVE)
        if path.suffix.casefold() in {".csv", ".txt"}:
            return InputSource(path, InputSourceKind.FILE)
        raise ValueError("Seleccione una carpeta GTFS, un ZIP o un CSV/TXT compatible.")

    def _show_import_progress(self, progress: ImportProgress) -> None:
        self._progress_bar.setValue(round(progress.fraction * 100))
        self._status_label.setText(f"Importando: {progress.phase.value.lower()}.")
        self._content_label.setText(self._status_label.text())

    def _import_finished(self, result: ImportFeedResult) -> None:
        self._progress_bar.hide()
        self.job_finished()
        self._refresh_overview()
        if result.state is JobState.READY:
            QMessageBox.information(
                self,
                "Importación completada",
                "El feed se ha importado correctamente.",
                QMessageBox.StandardButton.Ok,
            )
        elif result.state is JobState.CANCELLED:
            QMessageBox.information(
                self,
                "Importación cancelada",
                "La importación se ha cancelado limpiamente.",
                QMessageBox.StandardButton.Ok,
            )
        else:
            self._show_error(
                "La importación no se ha completado. "
                f"Estado: {result.state.value}; incidencias: {result.issue_count}."
            )

    def _import_failed(self, message: str) -> None:
        self._progress_bar.hide()
        self.job_finished()
        self._show_error(f"No se pudo iniciar la importación: {message}")

    def _show_error(self, message: str) -> None:
        self._error_sequence += 1
        error_code = f"UI-{self._error_sequence:04d}"
        self._logger.error(
            "APPLICATION_ERROR code=%s context=%s",
            error_code,
            safe_context({"event": "ui_error", "error_code": error_code}),
            exc_info=self._debug,
        )
        dialog = QMessageBox(
            QMessageBox.Icon.Critical,
            "GTFS Explorer",
            "No se ha podido completar la operación.",
            parent=self,
        )
        dialog.setInformativeText(f"Código de diagnóstico: {error_code}.")
        if self._debug:
            dialog.setDetailedText(message)
        if self._logs_directory is not None:
            export_button = dialog.addButton(
                "Exportar diagnóstico…", QMessageBox.ButtonRole.ActionRole
            )
        else:
            export_button = None
        dialog.exec()
        if dialog.clickedButton() is export_button:
            self._export_diagnostics()

    def _export_diagnostics(self) -> None:
        if self._logs_directory is None:
            return
        preview = preview_diagnostics(self._logs_directory)
        if not preview.files:
            QMessageBox.information(
                self,
                "Diagnóstico",
                "No hay logs locales para exportar.",
                QMessageBox.StandardButton.Ok,
            )
            return
        if (
            QMessageBox.question(self, "Previsualización del diagnóstico", preview.summary())
            is not QMessageBox.StandardButton.Yes
        ):
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Guardar diagnóstico", "gtfs-explorer-diagnostico.zip", "ZIP (*.zip)"
        )
        if not destination:
            return
        try:
            export_diagnostics(preview, Path(destination).with_suffix(".zip"))
        except OSError:
            QMessageBox.warning(
                self, "Diagnóstico", "No se ha podido guardar el diagnóstico local."
            )
            return
        QMessageBox.information(
            self,
            "Diagnóstico",
            "Diagnóstico local exportado.",
            QMessageBox.StandardButton.Ok,
        )

    def _apply_state(self) -> None:
        for action, widget_action in self._actions.items():
            widget_action.setEnabled(self._state.allows(action))
        self._status_label.setText(self._state.status_message)
        self._content_label.setText(self._state.status_message)
        self._navigation.setEnabled(self._state.mode is not UiMode.NO_PROJECT)

    def _refresh_overview(self) -> None:
        if self._opened_project is None:
            self._overview.clear()
            return
        try:
            with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
                overview = FeedOverviewQueries(unit_of_work.overview).get()
        except Exception as error:
            self._show_error(f"No se pudo actualizar el resumen del feed: {error}")
            return
        self._overview.show_overview(overview)
        self._exporter.set_executor(self._export_feed)
        specification = load_schedule_spec(_SPECIFICATION_PATH)
        self._raw_inspector.configure(
            {
                file.name: tuple(specification.files[file.name].fields)
                for file in overview.files
                if file.known_to_schedule_spec and file.row_count is not None
            }
        )
        self._explorer.refresh()

    def _with_route_queries(self, query: Callable[[RouteExplorerQueries], object]) -> object:
        if self._opened_project is None:
            raise RuntimeError("Abra un proyecto antes de explorar sus rutas.")
        with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
            return query(RouteExplorerQueries(unit_of_work.route_explorer))

    def _query_routes(self) -> PagedResult[RouteSummary]:
        return self._with_route_queries(lambda queries: queries.routes(PageRequest()))  # type: ignore[return-value]

    def _query_services(self, route_id: str) -> PagedResult[ServiceSummary]:
        return self._with_route_queries(
            lambda queries: queries.services_for_route(route_id, PageRequest())
        )  # type: ignore[return-value]

    def _query_directions(self, route_id: str, service_id: str) -> PagedResult[DirectionSummary]:
        return self._with_route_queries(
            lambda queries: queries.directions_for_route_service(
                route_id, service_id, PageRequest()
            )
        )  # type: ignore[return-value]

    def _query_trips(
        self, route_id: str, service_id: str, direction_id: int | None
    ) -> PagedResult[TripSummary]:
        return self._with_route_queries(
            lambda queries: queries.trips_for_route_service_direction(
                route_id, service_id, direction_id, PageRequest()
            )
        )  # type: ignore[return-value]

    def _query_timeline(self, trip_id: str) -> PagedResult[TimelineStop]:
        return self._with_route_queries(
            lambda queries: queries.trip_timeline(trip_id, PageRequest(limit=500))
        )  # type: ignore[return-value]

    def _query_map_layers(self, trip_id: str) -> MapLayerPayload:
        if self._opened_project is None:
            raise RuntimeError("Abra un proyecto antes de consultar el mapa.")
        with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
            geometry = GeometryQueries(unit_of_work.geometry).trip_shape(trip_id)
        return map_layers_for_trip(geometry)

    def _query_stop(self, stop_id: str) -> StopInspection:
        if self._opened_project is None:
            raise RuntimeError("Abra un proyecto antes de inspeccionar una parada.")
        with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
            return StopInspectorQueries(unit_of_work.stop_inspector).inspect(
                stop_id, page=PageRequest()
            )

    def _query_timetable(
        self, route_id: str, service_id: str, direction_id: int | None
    ) -> TimetableMatrix:
        if self._opened_project is None:
            raise RuntimeError("Abra un proyecto antes de consultar horarios.")
        with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
            return TimetableQueries(unit_of_work.route_explorer).matrix(
                route_id, service_id, direction_id
            )

    def _query_raw(self, request: RawQuery) -> RawPage:
        if self._opened_project is None:
            raise RuntimeError("Abra un proyecto antes de consultar el staging raw.")
        with DuckDbUnitOfWork(
            self._opened_project.database, load_schedule_spec(_SPECIFICATION_PATH)
        ) as unit_of_work:
            if unit_of_work.raw is None:
                raise RuntimeError("El inspector raw no está disponible.")
            return RawInspectorQueries(unit_of_work.raw).query(request)

    def _query_validation(
        self, report_filter: ValidationIssueFilter, page: PageRequest
    ) -> PagedResult[ValidationIssueSummary]:
        if self._opened_project is None:
            raise RuntimeError("Abra un proyecto antes de consultar las incidencias.")
        with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
            return ValidationQueries(unit_of_work.validation).issues(report_filter, page)

    def _show_section(self, index: int) -> None:
        explorer_visible = index == 1
        validation_visible = index == 2
        export_visible = index == 3
        self._explore_tabs.setVisible(explorer_visible)
        self._validation.setVisible(validation_visible)
        self._exporter.setVisible(export_visible)
        self._overview.setVisible(not (explorer_visible or validation_visible or export_visible))
        if explorer_visible:
            self._content_label.setText("Explore rutas, viajes, paradas y horarios programados.")
        elif validation_visible:
            self._content_label.setText("Revise incidencias sin puntuaciones agregadas.")
            self._validation.refresh()
        elif export_visible:
            self._content_label.setText(
                "Exporte una salida local con alcance y formato explícitos."
            )

    def _export_feed(
        self, request: ExportRequest, is_cancelled: Callable[[], bool]
    ) -> ExportResult:
        """Compone exportadores ya verificados sin filtrar SQL a la interfaz Qt."""
        if self._opened_project is None:
            raise RuntimeError("Abra un proyecto antes de exportar.")
        selection = SubsetSelection(
            request.route_ids,
            request.trip_ids or None,
            request.service_ids or None,
        )
        with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
            feed = unit_of_work.feeds.latest_metadata()
            if feed is None:
                raise RuntimeError("El proyecto no contiene un feed importado.")
            connection = unit_of_work._connection
            if request.format is ExportFormat.JSON:
                manifest = JsonBundleExporter().write(
                    connection,
                    request.destination,
                    feed_id=feed.feed_id,
                    selection=JsonExportSelection(
                        request.route_ids, request.trip_ids, request.service_ids
                    ),
                    overwrite=request.overwrite,
                    is_cancelled=is_cancelled,
                )
                return ExportResult(manifest, classification="derivada")
            if request.format is ExportFormat.GEOJSON:
                manifest = GeoJsonExporter().write(
                    connection,
                    request.destination,
                    selection=GeoJsonExportSelection(
                        request.route_ids, request.trip_ids, request.service_ids
                    ),
                    include_bbox=request.include_bbox,
                    overwrite=request.overwrite,
                    is_cancelled=is_cancelled,
                )
                return ExportResult(manifest, classification="compatible")
            if request.format is ExportFormat.CSV:
                rows = connection.execute(
                    "SELECT route_id, route_short_name, route_long_name, "
                    "CAST(route_type AS VARCHAR) FROM gtfs_routes WHERE route_id IN ("
                    + ",".join("?" for _ in request.route_ids)
                    + ") ORDER BY route_id, source_row",
                    sorted(request.route_ids),
                ).fetchall()
                mode = (
                    CsvExportMode.SPREADSHEET_SAFE
                    if request.spreadsheet_safe
                    else CsvExportMode.FAITHFUL
                )
                manifest = CsvExporter().write(
                    request.destination,
                    headers=("route_id", "route_short_name", "route_long_name", "route_type"),
                    rows=rows,
                    options=CsvExportOptions(mode),
                    overwrite=request.overwrite,
                    is_cancelled=is_cancelled,
                )
                return ExportResult(manifest, classification="compatible")
            subset = MiniGtfsSubsetQueries(unit_of_work.core_subset).close(selection)
            specification = load_schedule_spec(_SPECIFICATION_PATH)
            manifest = MiniGtfsSubsetExporter(specification).write(
                request.destination,
                self._mini_gtfs_tables(connection, specification, subset),
                expected=subset,
                overwrite=request.overwrite,
                is_cancelled=is_cancelled,
            )
            return ExportResult(
                manifest,
                ("Los opcionales no incluidos se han omitido explícitamente.",),
                "oficial",
            )

    @staticmethod
    def _mini_gtfs_tables(
        connection: DatabaseConnection, specification: ScheduleSpec, subset: CoreSubset
    ) -> tuple[MiniGtfsTable, ...]:
        filters = {
            "agency.txt": ("gtfs_agency", "agency_id", subset.agency_ids),
            "routes.txt": ("gtfs_routes", "route_id", subset.route_ids),
            "trips.txt": ("gtfs_trips", "trip_id", subset.trip_ids),
            "stops.txt": ("gtfs_stops", "stop_id", subset.stop_ids),
            "stop_times.txt": ("gtfs_stop_times", "trip_id", subset.trip_ids),
            "calendar.txt": ("gtfs_calendar", "service_id", subset.calendar_service_ids),
            "calendar_dates.txt": (
                "gtfs_calendar_dates",
                "service_id",
                subset.calendar_date_service_ids,
            ),
        }
        tables: list[MiniGtfsTable] = []
        for filename, (table, column, values) in filters.items():
            if not values:
                continue
            headers = tuple(specification.files[filename].fields)
            rows = connection.execute(
                f"SELECT raw_values FROM {table} WHERE {column} IN "
                f"({','.join('?' for _ in values)}) ORDER BY source_row",
                sorted(values),
            ).fetchall()
            materialized = tuple(
                tuple(json.loads(row[0]).get(header) for header in headers) for row in rows
            )
            tables.append(MiniGtfsTable(filename, headers, materialized))
        # ``shape_id`` es opcional en trips.txt, pero si se conserva su valor
        # también debe conservarse la geometría referenciada; de lo contrario
        # la reimportación formal rechaza el Mini-GTFS resultante.
        if subset.trip_ids:
            headers = tuple(specification.files["shapes.txt"].fields)
            rows = connection.execute(
                "SELECT DISTINCT sh.raw_values FROM gtfs_shapes sh "
                "JOIN gtfs_trips t ON t.shape_id = sh.shape_id "
                "WHERE t.trip_id IN ("
                + ",".join("?" for _ in subset.trip_ids)
                + ") ORDER BY sh.shape_id, sh.shape_pt_sequence, sh.source_row",
                sorted(subset.trip_ids),
            ).fetchall()
            if rows:
                materialized = tuple(
                    tuple(json.loads(row[0]).get(header) for header in headers) for row in rows
                )
                tables.append(MiniGtfsTable("shapes.txt", headers, materialized))
        return tuple(tables)

    def _show_validation(self) -> None:
        self._navigation.setCurrentRow(2)

    def _select_map_package(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Seleccionar paquete de mapa offline")
        if not directory:
            return
        try:
            attribution = self._explorer.set_map_package(Path(directory))
        except (OSError, ValueError, RuntimeError) as error:
            self._map_package_status.setText("Paquete rechazado: se mantiene el fondo neutro.")
            self._show_error(f"No se pudo abrir el paquete de mapa: {error}")
            return
        self._map_package_status.setText(f"Paquete offline activo. Atribución: {attribution}")

    def _show_validation_raw(
        self, filename: str, field_name: str | None, entity_id: str | None
    ) -> None:
        self._navigation.setCurrentRow(1)
        self._explore_tabs.setCurrentWidget(self._raw_inspector)
        self._raw_inspector.inspect_location(filename, field_name, entity_id)

    def _show_validation_help(self, help_id: str) -> None:
        self._show_help(help_id)

    def _show_help(self, help_id: str | None = None) -> None:
        HelpDialog(self._help_catalog, help_id, self).exec()

    def _export_validation_report(
        self, batch_id: str, report_filter: ValidationIssueFilter
    ) -> None:
        destination, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar informe de validación",
            "informe-validacion.html",
            "HTML (*.html);;JSON (*.json)",
        )
        if not destination or self._opened_project is None:
            return
        path = Path(destination)
        report_format: ReportFormat = "json" if selected_filter.startswith("JSON") else "html"
        if path.suffix.casefold() != f".{report_format}":
            path = path.with_suffix(f".{report_format}")
        if (
            path.exists()
            and QMessageBox.question(
                self, "Sobrescribir informe", f"Ya existe '{path.name}'. ¿Sobrescribir?"
            )
            is not QMessageBox.StandardButton.Yes
        ):
            return
        try:
            with self._opened_project.database.connection() as connection:
                ValidationReportExporter().write(
                    connection,
                    path,
                    batch_id=batch_id,
                    report_format=report_format,
                    report_filter=ValidationReportFilter(
                        report_filter.severities, report_filter.categories
                    ),
                    overwrite=path.exists(),
                )
        except Exception as error:
            self._show_error(f"No se pudo exportar el informe: {error}")
            return
        QMessageBox.information(
            self,
            "Informe exportado",
            f"Informe guardado en '{path.name}'.",
            QMessageBox.StandardButton.Ok,
        )


def run_window(
    *, logger: logging.Logger | None = None, logs_directory: Path | None = None, debug: bool = False
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(logger=logger, logs_directory=logs_directory, debug=debug)
    window.show()
    return app.exec()
