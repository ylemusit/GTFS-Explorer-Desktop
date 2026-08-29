"""Shell Qt que refleja el estado global sin duplicar reglas de acciones."""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.application.commands.create_project import CreateProject
from gtfs_explorer.application.commands.import_feed import ImportFeed, ImportFeedResult
from gtfs_explorer.application.commands.open_project import OpenedProject, OpenProject
from gtfs_explorer.application.commands.recover_workspace import RestoreWorkspace
from gtfs_explorer.application.exporting import FeedExportLifecycle
from gtfs_explorer.application.jobs.import_job import (
    ImportPhase,
    ImportProgress,
    ProgressMode,
)
from gtfs_explorer.application.map_policy import MapMode, normalize_map_mode
from gtfs_explorer.application.queries.feed_overview import FeedOverviewQueries
from gtfs_explorer.application.queries.geometry import GeometryQueries
from gtfs_explorer.application.queries.map_layers import MapLayerPayload, map_layers_for_trip
from gtfs_explorer.application.queries.project_map_coverage import project_map_coverage
from gtfs_explorer.application.queries.raw import RawInspectorQueries
from gtfs_explorer.application.queries.routes import RouteExplorerQueries
from gtfs_explorer.application.queries.stops import StopInspectorQueries
from gtfs_explorer.application.queries.subset import MiniGtfsSubsetQueries
from gtfs_explorer.application.queries.timetable import TimetableMatrix, TimetableQueries
from gtfs_explorer.application.queries.validation import ValidationQueries
from gtfs_explorer.application.settings import DirectoryPreferences
from gtfs_explorer.application.ui_state import UiAction, UiMode, UiState
from gtfs_explorer.domain.operations import Operation, OperationStatus, OperationType
from gtfs_explorer.domain.overview import ValidationOverview
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
from gtfs_explorer.infrastructure.filesystem.paths import (
    ApplicationPaths,
    DirectoryKind,
    application_resource_path,
    resolve_application_paths,
)
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    save_project_descriptor,
)
from gtfs_explorer.infrastructure.filesystem.workspace_recovery import (
    BackupCandidate,
    RecoveryCandidateAvailableError,
)
from gtfs_explorer.infrastructure.logging import (
    capture_application_error,
    export_diagnostics,
    preview_diagnostics,
)
from gtfs_explorer.infrastructure.maps.offline_library import OfflineMapLibrary, resolve_best_map
from gtfs_explorer.presentation.desktop.about import AboutDialog
from gtfs_explorer.presentation.desktop.exporter import (
    ExportAssistantWidget,
    ExportFormat,
    ExportRequest,
    ExportResult,
)
from gtfs_explorer.presentation.desktop.help import HelpCatalog, HelpDialog
from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.presentation.desktop.import_adapter import ImportJobAdapter
from gtfs_explorer.presentation.desktop.overview.history import OperationHistoryWidget
from gtfs_explorer.presentation.desktop.overview.widget import FeedOverviewWidget
from gtfs_explorer.presentation.desktop.raw.widget import RawInspectorWidget
from gtfs_explorer.presentation.desktop.routes.widget import RouteExplorerWidget
from gtfs_explorer.presentation.desktop.startup_intro import StartupIntroDialog
from gtfs_explorer.presentation.desktop.validation.widget import ValidationWidget
from gtfs_explorer.product import IDENTITY, runtime_architecture, runtime_build_id

_SPECIFICATION_PATH = application_resource_path(
    f"schemas/gtfs_schedule/{IDENTITY.gtfs_spec_revision}/spec.json"
)


def _closed_reference_query(subset: CoreSubset, filename: str) -> tuple[str, list[object]]:
    references: tuple[tuple[str, frozenset[str]], ...]
    if filename == "transfers":
        references = (
            ("from_stop_id", subset.stop_ids),
            ("to_stop_id", subset.stop_ids),
            ("from_route_id", subset.route_ids),
            ("to_route_id", subset.route_ids),
            ("from_trip_id", subset.trip_ids),
            ("to_trip_id", subset.trip_ids),
        )
    elif filename == "attributions":
        references = (
            ("agency_id", subset.agency_ids),
            ("route_id", subset.route_ids),
            ("trip_id", subset.trip_ids),
        )
    else:
        raise ValueError(f"Archivo opcional no soportado: {filename}")

    predicates: list[str] = []
    parameters: list[object] = []
    for column, values in references:
        if values:
            predicates.append(
                f"({column} IS NULL OR {column} IN ({','.join('?' for _ in values)}))"
            )
            parameters.extend(sorted(values))
        else:
            predicates.append(f"{column} IS NULL")
    return " AND ".join(predicates), parameters


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
        application_paths: ApplicationPaths | None = None,
        logger: logging.Logger | None = None,
        logs_directory: Path | None = None,
        debug: bool = False,
        elapsed_clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__()
        self._has_persistent_paths = application_paths is not None
        self._application_paths = application_paths or resolve_application_paths(Path(sys.argv[0]))
        self._directory_preferences = DirectoryPreferences(
            self._application_paths,
            persist=self._has_persistent_paths,
        )
        self._offline_map_library = (
            OfflineMapLibrary(self._application_paths.maps_directory)
            if self._has_persistent_paths
            else OfflineMapLibrary()
        )
        self._state = UiState()
        self._cancel_active_job = cancel_active_job
        self._opened_project: OpenedProject | None = None
        self._import_command_factory = import_command_factory
        self._logger = logger or logging.getLogger("gtfs_explorer")
        self._logs_directory = logs_directory or (
            self._application_paths.logs_directory if self._has_persistent_paths else None
        )
        self._debug = debug
        self._elapsed_clock = elapsed_clock or time.monotonic
        self._error_sequence = 0
        self._import_feed_name: str | None = None
        self._import_phase: ImportPhase | None = None
        self._import_progress = 0
        self._import_progress_mode = ProgressMode.INDETERMINATE
        self._import_detail: str | None = None
        self._import_completed: int | None = None
        self._import_unit: str | None = None
        self._import_started_at: float | None = None
        application = QApplication.instance()
        if application is not None:
            application.setApplicationName(IDENTITY.name)
            application.setApplicationVersion(IDENTITY.version)
        self._import_adapter = ImportJobAdapter(self)
        self._import_adapter.started.connect(self._import_job_started)
        self._import_adapter.progress.connect(self._show_import_progress)
        self._import_adapter.finished.connect(self._import_finished)
        self._import_adapter.failed.connect(self._import_failed)
        self._import_timer = QTimer(self)
        self._import_timer.setInterval(1000)
        self._import_timer.timeout.connect(self._update_import_elapsed)
        self.setWindowTitle(
            t("identity.main_window_title", product_name=IDENTITY.name, version=IDENTITY.version)
        )
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
            self._show_error(str(error), operation="import_source", exception=error)
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
        self._content_label.setAccessibleName(t("accessibility.current_state"))
        layout.addWidget(self._content_label)
        self._import_context_label = QLabel()
        self._import_context_label.setObjectName("importContext")
        self._import_context_label.setWordWrap(True)
        self._import_context_label.setAccessibleName(t("accessibility.import_context"))
        self._import_context_label.hide()
        layout.addWidget(self._import_context_label)
        self._overview = FeedOverviewWidget(self._show_validation)
        layout.addWidget(self._overview, 1)
        self._operation_history = OperationHistoryWidget(self._query_operations)
        layout.addWidget(self._operation_history, 1)
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
        self._raw_inspector = RawInspectorWidget(
            self._query_raw,
            export_directory_resolver=lambda: self._directory_preferences.initial_directory(
                DirectoryKind.EXPORTS
            ),
            prepare_export_directory=lambda: self._prepare_directory(DirectoryKind.EXPORTS),
            on_export_directory_used=lambda directory: self._remember_directory(
                DirectoryKind.EXPORTS, directory
            ),
        )
        self._validation = ValidationWidget(
            self._query_validation,
            list_files=self._query_validation_files,
            query_summary=self._query_validation_summary,
            navigate_to_raw=self._show_validation_raw,
            show_help=self._show_validation_help,
            export_report=self._export_validation_report,
        )
        self._exporter = ExportAssistantWidget(
            executor=self._export_feed_from_ui,
            default_directory_resolver=lambda: self._directory_preferences.initial_directory(
                DirectoryKind.EXPORTS
            ),
            prepare_default_directory=lambda: self._prepare_directory(DirectoryKind.EXPORTS),
            on_destination_directory_used=lambda directory: self._remember_directory(
                DirectoryKind.EXPORTS, directory
            ),
        )
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
        map_mode_label = QLabel(t("settings.map_mode_label"), settings_widget)
        self._map_mode_combo = QComboBox(settings_widget)
        self._map_mode_combo.setObjectName("mapModeSelector")
        self._map_mode_combo.setAccessibleName(t("settings.map_mode_label"))
        self._map_mode_combo.addItem(t("settings.map_mode_auto"), MapMode.AUTO)
        self._map_mode_combo.addItem(t("settings.map_mode_offline"), MapMode.OFFLINE)
        self._map_mode_combo.addItem(t("settings.map_mode_online"), MapMode.ONLINE)
        map_mode_label.setBuddy(self._map_mode_combo)
        settings_layout.addWidget(map_mode_label)
        settings_layout.addWidget(self._map_mode_combo)
        self._map_policy_status = QLabel(self._explorer.map_status, settings_widget)
        self._map_policy_status.setObjectName("mapPolicyStatus")
        self._map_policy_status.setWordWrap(True)
        settings_layout.addWidget(self._map_policy_status)
        map_label = QLabel(t("settings.map_label"), settings_widget)
        settings_layout.addWidget(map_label)
        choose_map = QPushButton(t("settings.choose_map"), settings_widget)
        choose_map.setAccessibleDescription(t("settings.choose_map_description"))
        choose_map.setObjectName("selectMapPackage")
        choose_map.setAccessibleName(t("settings.choose_map"))
        choose_map.setToolTip(t("settings.choose_map_description"))
        choose_map.clicked.connect(self._select_map_package)
        settings_layout.addWidget(choose_map)
        import_pmtiles = QPushButton(t("settings.import_pmtiles"), settings_widget)
        import_pmtiles.setObjectName("importPmtiles")
        import_pmtiles.setAccessibleName(t("settings.import_pmtiles"))
        import_pmtiles.setToolTip(t("settings.import_pmtiles"))
        import_pmtiles.clicked.connect(self._import_pmtiles)
        settings_layout.addWidget(import_pmtiles)
        self._map_package_status = QLabel(t("settings.map_empty"))
        self._map_package_status.setWordWrap(True)
        settings_layout.addWidget(self._map_package_status)
        offline_maps_label = QLabel(t("settings.offline_maps"), settings_widget)
        settings_layout.addWidget(offline_maps_label)
        self._offline_maps = QTableWidget(0, 6, settings_widget)
        self._offline_maps.setObjectName("offlineMapsTable")
        self._offline_maps.setHorizontalHeaderLabels(
            (
                t("settings.map_name"),
                t("settings.map_type"),
                t("settings.map_coverage"),
                t("settings.map_size"),
                t("settings.map_status"),
                t("settings.map_source_version"),
            )
        )
        self._offline_maps.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._offline_maps.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._offline_maps.setAccessibleName(t("settings.offline_maps"))
        settings_layout.addWidget(self._offline_maps)
        remove_map = QPushButton(t("settings.remove_map"), settings_widget)
        remove_map.setObjectName("removeOfflineMap")
        remove_map.setAccessibleName(t("settings.remove_map"))
        remove_map.setToolTip(t("settings.remove_map"))
        remove_map.clicked.connect(self._remove_selected_offline_map)
        settings_layout.addWidget(remove_map)
        self._refresh_offline_maps()
        settings_layout.addStretch()
        self._map_mode_combo.currentIndexChanged.connect(self._set_map_mode)
        settings.setWidget(settings_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, settings)
        settings.hide()
        self._settings_dock = settings
        self._status_label = QLabel()
        self._status_label.setAccessibleName(t("accessibility.application_state"))
        self.statusBar().addWidget(self._status_label)
        self._project_identity_label = QLabel()
        self._project_identity_label.setObjectName("projectIdentityStatus")
        self._project_identity_label.setAccessibleName(t("accessibility.project_identity"))
        self.statusBar().addPermanentWidget(self._project_identity_label, 1)
        self._progress_bar = QProgressBar()
        self._progress_bar.setAccessibleName(t("accessibility.import_progress"))
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
        self._about_action = QAction(t("action.about"), self)
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
        self._about_action.triggered.connect(self._show_about)
        toolbar = QToolBar(t("toolbar.title"), self)
        toolbar.setAccessibleName(t("toolbar.title"))
        self.addToolBar(toolbar)
        for toolbar_action in self._actions.values():
            toolbar.addAction(toolbar_action)
        toolbar.addAction(self._help_action)
        toolbar.addAction(self._about_action)

    def _request_cancellation(self) -> None:
        if not self._state.allows(UiAction.CANCEL_JOB):
            return
        self._state = self._state.cancellation_requested()
        self._apply_state()
        self._render_import_context()
        if self._cancel_active_job is not None:
            self._cancel_active_job()
        self._import_adapter.cancel()

    def _dialog_directory(self, kind: DirectoryKind) -> Path:
        """Resuelve el inicio útil del diálogo y crea el default solo al usarlo."""

        if self._has_persistent_paths:
            return self._directory_preferences.dialog_directory(kind)
        return self._directory_preferences.initial_directory(kind)

    def _prepare_directory(self, kind: DirectoryKind) -> Path:
        """Prepara una carpeta de usuario para la operación actual."""

        if self._has_persistent_paths:
            return self._directory_preferences.dialog_directory(kind)
        return self._directory_preferences.initial_directory(kind)

    def _remember_directory(self, kind: DirectoryKind, directory: Path) -> None:
        """Persiste solo preferencias locales; los contratos de proyecto no cambian."""

        self._directory_preferences.remember(kind, directory)

    def _remember_file_directory(self, kind: DirectoryKind, file_path: Path) -> None:
        self._directory_preferences.remember_file(kind, file_path)

    def _choose_project(self) -> None:
        start_directory = self._dialog_directory(DirectoryKind.PROJECTS)
        directory = QFileDialog.getExistingDirectory(
            self, t("dialog.open_project_title"), str(start_directory)
        )
        if not directory:
            return
        try:
            self._close_project()
            opened = OpenProject(Path(directory)).execute()
        except RecoveryCandidateAvailableError as error:
            candidate = self._choose_recovery_candidate(error)
            if candidate is None:
                return
            try:
                RestoreWorkspace(Path(directory)).execute(candidate)
                opened = OpenProject(Path(directory)).execute()
            except Exception as recovery_error:
                self._show_error(
                    str(recovery_error), operation="restore_workspace", exception=recovery_error
                )
                return
        except Exception as error:
            self._show_error(str(error), operation="open_project", exception=error)
            return
        self._opened_project = opened
        self.project_opened(
            recovery_required=opened.descriptor.status == ProjectStatus.RECOVERY_REQUIRED
        )
        self._remember_directory(DirectoryKind.PROJECTS, Path(directory))
        self._refresh_overview()
        self._resolve_global_map()

    def _choose_recovery_candidate(
        self,
        error: RecoveryCandidateAvailableError,
    ) -> BackupCandidate | None:
        candidates = [
            candidate for candidate in error.inspection.backup_candidates if candidate.valid
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            candidate = candidates[0]
            description = (
                f"Nombre: {candidate.name}\n"
                f"Fecha: {candidate.modified_at}\n"
                f"Esquema: {candidate.schema_version}"
            )
        else:
            labels = [
                f"{candidate.name} · {candidate.modified_at} · schema {candidate.schema_version}"
                for candidate in candidates
            ]
            label, accepted = QInputDialog.getItem(
                self,
                t("dialog.recovery_candidates_title"),
                t("dialog.recovery_candidates_prompt"),
                labels,
                0,
                False,
            )
            if not accepted:
                return None
            candidate = candidates[labels.index(label)]
            description = label
        confirmation = QMessageBox.question(
            self,
            t("dialog.recovery_restore_title"),
            t("dialog.recovery_restore_message", description=description),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return candidate if confirmation is QMessageBox.StandardButton.Yes else None

    def _choose_new_project(self) -> None:
        start_directory = self._dialog_directory(DirectoryKind.PROJECTS)
        directory = QFileDialog.getExistingDirectory(
            self, t("dialog.new_project_title"), str(start_directory)
        )
        if not directory:
            return
        try:
            self._close_project()
            opened = CreateProject(Path(directory)).execute()
        except Exception as error:
            self._show_error(str(error), operation="create_project", exception=error)
            return
        self._opened_project = opened
        self.project_opened()
        self._remember_directory(DirectoryKind.PROJECTS, Path(directory))
        self._refresh_overview()
        self._resolve_global_map()

    def _close_project(self) -> None:
        opened_project = self._opened_project
        # Desacopla primero los widgets y el estado global. Algunos widgets
        # reciben señales durante su reset y no deben conservar el proyecto
        # que se está cerrando como contexto consultable.
        self._opened_project = None
        self._clear_import_context()
        self._reset_project_ui_context()
        if opened_project is not None:
            try:
                opened_project.close()
            except Exception as error:
                self._show_error(
                    f"No se pudo cerrar el proyecto: {error}",
                    operation="close_project",
                    exception=error,
                )
        if self._state.mode not in {UiMode.NO_PROJECT, UiMode.JOB_RUNNING, UiMode.JOB_CANCELLING}:
            self.project_closed()

    def _reset_project_ui_context(self) -> None:
        """Deja toda la UI transitoria sin identidad ni datos de proyecto."""
        self._overview.clear()
        self._operation_history.clear()
        self._raw_inspector.clear()
        self._explorer.clear()
        self._validation.clear()
        self._exporter.clear()
        self._exporter.set_executor(None)
        self._explore_tabs.setCurrentWidget(self._explorer)
        self._navigation.blockSignals(True)
        self._navigation.setCurrentRow(0)
        self._navigation.blockSignals(False)
        self._show_section(0)

    def _choose_import_source(self) -> None:
        choice = QMessageBox.question(
            self,
            t("dialog.import_source_title"),
            t("dialog.import_source_message"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice is QMessageBox.StandardButton.Yes:
            start_directory = self._dialog_directory(DirectoryKind.IMPORTS)
            selected = QFileDialog.getExistingDirectory(
                self, t("dialog.import_folder_title"), str(start_directory)
            )
        else:
            start_directory = self._dialog_directory(DirectoryKind.IMPORTS)
            selected, _ = QFileDialog.getOpenFileName(
                self,
                t("dialog.import_file_title"),
                str(start_directory),
                filter=t("dialog.import_file_filter"),
            )
        if not selected:
            return
        try:
            selected_path = Path(selected)
            source = self._source_from_path(selected_path)
            self._remember_directory(DirectoryKind.IMPORTS, selected_path)
            self._request_import(source)
        except ValueError as error:
            self._show_error(str(error), operation="import_source", exception=error)

    def _request_import(self, source: InputSource) -> None:
        if not self._state.allows(UiAction.IMPORT_FEED):
            raise ValueError("Abra un proyecto listo antes de importar un feed.")
        confirm = QMessageBox.question(
            self,
            t("dialog.confirm_import_title"),
            t("dialog.confirm_import_message", source_name=source.path.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm is not QMessageBox.StandardButton.Yes:
            return
        self.start_import(source)

    def start_import(self, source: InputSource) -> None:
        """Inicia el trabajo desde una interacción ya confirmada de la UI."""
        if not self._state.allows(UiAction.IMPORT_FEED):
            raise RuntimeError("No se puede importar en el estado actual.")
        self.job_started()
        self._begin_import_context(source)
        self._progress_bar.setValue(0)
        self._progress_bar.setRange(0, 0)
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
        if self._import_feed_name is None:
            return
        self._import_phase = progress.phase
        self._import_progress_mode = progress.mode
        self._import_detail = progress.detail
        self._import_completed = progress.completed
        self._import_unit = progress.unit
        if progress.mode is ProgressMode.DETERMINATE:
            self._import_progress = round(progress.fraction * 100)
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(self._import_progress)
        else:
            self._progress_bar.setRange(0, 0)
        self._render_import_context()

    def _begin_import_context(self, source: InputSource) -> None:
        self._clear_import_context()
        self._import_feed_name = source.path.name
        self._import_phase = None
        self._import_progress = 0
        self._import_progress_mode = ProgressMode.DETERMINATE
        self._import_detail = None
        self._import_completed = None
        self._import_unit = None
        self._import_context_label.show()
        self._render_import_context()

    def _import_job_started(self) -> None:
        if self._import_feed_name is None:
            return
        self._import_started_at = self._elapsed_clock()
        self._import_timer.start()
        self._render_import_context()

    def _update_import_elapsed(self) -> None:
        if self._import_started_at is not None:
            self._render_import_context()

    def _elapsed_text(self) -> str:
        if self._import_started_at is None:
            return "00:00"
        elapsed = max(0, int(self._elapsed_clock() - self._import_started_at))
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _import_phase_text(phase: ImportPhase | None) -> str:
        if phase is None:
            return "Preparación"
        return {
            ImportPhase.PREFLIGHT: "Preparación",
            ImportPhase.STAGING: "Carga",
            ImportPhase.NORMALIZING: "Normalización",
            ImportPhase.VALIDATING: "Validación",
            ImportPhase.COMMITTING: "Finalización",
            ImportPhase.CLEANUP: "Limpieza",
        }[phase]

    def _render_import_context(self) -> None:
        if self._import_feed_name is None:
            return
        cancellation = self._state.mode is UiMode.JOB_CANCELLING
        prefix = "Cancelando…" if cancellation else "Importación activa"
        phase = self._import_phase_text(self._import_phase)
        elapsed = self._elapsed_text()
        if self._import_progress_mode is ProgressMode.DETERMINATE:
            progress_text = f"Progreso: {self._import_progress} %"
            compact_progress = f"{self._import_progress} %"
        elif self._import_completed is not None:
            unit = self._import_unit or "unidades"
            progress_text = f"Actividad: {self._import_completed:,} {unit}".replace(",", ".")
            compact_progress = f"{self._import_completed:,} {unit}".replace(",", ".")
        else:
            progress_text = "Actividad en curso"
            compact_progress = "en curso"
        detail = f"\nDetalle: {self._import_detail}" if self._import_detail else ""
        self._import_context_label.setText(
            f"{prefix}\nFeed: {self._import_feed_name}\nFase: {phase}\n"
            f"{progress_text}{detail}\nTiempo transcurrido: {elapsed}"
        )
        self._status_label.setText(
            f"{'Cancelando' if cancellation else 'Importando'}: {self._import_feed_name} · "
            f"{phase} · {compact_progress} · {elapsed}"
        )

    def _clear_import_context(self) -> None:
        self._import_timer.stop()
        self._import_started_at = None
        self._import_feed_name = None
        self._import_phase = None
        self._import_progress = 0
        self._import_progress_mode = ProgressMode.INDETERMINATE
        self._import_detail = None
        self._import_completed = None
        self._import_unit = None
        if hasattr(self, "_import_context_label"):
            self._import_context_label.clear()
            self._import_context_label.hide()

    def _import_finished(self, result: ImportFeedResult) -> None:
        self._clear_import_context()
        self._progress_bar.hide()
        self.job_finished()
        self._synchronize_project_descriptor()
        self._refresh_overview()
        self._resolve_global_map()
        if result.state is JobState.READY:
            QMessageBox.information(
                self,
                t("dialog.import_completed_title"),
                t("dialog.import_completed_message"),
                QMessageBox.StandardButton.Ok,
            )
        elif result.state is JobState.INVALID:
            QMessageBox.information(
                self,
                t("dialog.import_invalid_title"),
                t("dialog.import_invalid_message"),
                QMessageBox.StandardButton.Ok,
            )
        elif result.state is JobState.CANCELLED:
            QMessageBox.information(
                self,
                t("dialog.import_cancelled_title"),
                t("dialog.import_cancelled_message"),
                QMessageBox.StandardButton.Ok,
            )
        else:
            self._show_error(
                "La importación no se ha completado. "
                f"Estado: {result.state.value}; incidencias: {result.issue_count}.",
                operation="import_feed",
                exception=RuntimeError(
                    f"Estado {result.state.value}; incidencias: {result.issue_count}."
                ),
            )

    def _import_failed(self, message: str) -> None:
        self._clear_import_context()
        self._progress_bar.hide()
        self.job_finished()
        self._refresh_operation_history()
        self._show_error(
            f"No se pudo iniciar la importación: {message}",
            operation="import_feed",
            exception=RuntimeError(message),
        )

    def _diagnostic_context(self) -> dict[str, object]:
        context: dict[str, object] = {
            "event": "ui_error",
            "product": IDENTITY.name,
            "version": IDENTITY.version,
            "build_id": runtime_build_id(),
            "gtfs_spec_revision": IDENTITY.gtfs_spec_revision,
            "architecture": runtime_architecture(),
            "app_state": self._state.mode.value,
        }
        if self._opened_project is not None:
            context.update(
                {
                    "project_id": self._opened_project.descriptor.project_id,
                    "project_name": self._opened_project.descriptor.name,
                }
            )
        return context

    def _show_error(
        self,
        message: str,
        *,
        operation: str = "ui_error",
        exception: BaseException | None = None,
    ) -> None:
        self._error_sequence += 1
        error_code = f"UI-{self._error_sequence:04d}"
        capture_application_error(
            self._logger,
            error_code=error_code,
            operation=operation,
            exception=exception or RuntimeError(message),
            context=self._diagnostic_context(),
        )
        dialog = QMessageBox(
            QMessageBox.Icon.Critical,
            t("dialog.error_title"),
            t("dialog.error_message"),
            parent=self,
        )
        dialog.setInformativeText(t("dialog.error_code", error_code=error_code))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        if self._logs_directory is not None:
            export_button = dialog.addButton(
                t("dialog.export_diagnostic_action"), QMessageBox.ButtonRole.ActionRole
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
                t("dialog.diagnostic_title"),
                t("dialog.diagnostic_no_logs"),
                QMessageBox.StandardButton.Ok,
            )
            return
        if (
            QMessageBox.question(
                self,
                t("dialog.diagnostic_preview_title"),
                preview.summary(),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            is not QMessageBox.StandardButton.Yes
        ):
            return
        start_directory = self._prepare_directory(DirectoryKind.DIAGNOSTICS)
        destination, _ = QFileDialog.getSaveFileName(
            self,
            t("dialog.diagnostic_save_title"),
            str(start_directory / "gtfs-explorer-diagnostico.zip"),
            t("dialog.diagnostic_filter"),
        )
        if not destination:
            return
        destination_path = Path(destination).with_suffix(".zip")
        try:
            export_diagnostics(preview, destination_path)
        except OSError:
            QMessageBox.warning(
                self,
                t("dialog.diagnostic_title"),
                t("dialog.diagnostic_save_error"),
                QMessageBox.StandardButton.Ok,
            )
            return
        self._remember_file_directory(DirectoryKind.DIAGNOSTICS, destination_path)
        QMessageBox.information(
            self,
            t("dialog.diagnostic_title"),
            t("dialog.diagnostic_exported"),
            QMessageBox.StandardButton.Ok,
        )

    def _apply_state(self) -> None:
        for action, widget_action in self._actions.items():
            widget_action.setEnabled(self._state.allows(action))
        self._status_label.setText(self._state.status_message)
        self._content_label.setText(self._state.status_message)
        self._navigation.setEnabled(self._state.mode is not UiMode.NO_PROJECT)
        self._refresh_project_identity()

    def _refresh_project_identity(self) -> None:
        if self._opened_project is None:
            self._project_identity_label.setText("Sin proyecto abierto")
            self._project_identity_label.setToolTip("")
            self._overview.clear_project_identity()
            return
        name = self._opened_project.descriptor.name
        workspace = str(self._opened_project.directory)
        self._project_identity_label.setText(f"Proyecto: {name} · Workspace: {workspace}")
        self._project_identity_label.setToolTip(workspace)
        self._overview.show_project_identity(name, workspace)

    def _refresh_overview(self) -> None:
        if self._opened_project is None:
            self._overview.clear()
            self._operation_history.clear()
            return
        try:
            with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
                overview = FeedOverviewQueries(unit_of_work.overview).get()
        except Exception as error:
            self._show_error(
                f"No se pudo actualizar el resumen del feed: {error}",
                operation="refresh_overview",
                exception=error,
            )
            return
        self._overview.show_overview(overview)
        self._refresh_operation_history()
        self._exporter.set_executor(self._export_feed_from_ui)
        specification = load_schedule_spec(_SPECIFICATION_PATH)
        self._raw_inspector.configure(
            {
                file.name: tuple(specification.files[file.name].fields)
                for file in overview.files
                if file.known_to_schedule_spec and file.row_count is not None
            }
        )
        self._explorer.refresh()
        if self._validation.isVisible():
            # Si una importación termina mientras esta sección está abierta,
            # no dejamos en pantalla el lote del feed anterior.
            self._validation.refresh()

    def _synchronize_project_descriptor(self) -> None:
        """Publica en project.json los metadatos persistidos por la importación."""
        if self._opened_project is None:
            return
        try:
            with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
                project = unit_of_work.projects.metadata()
                if project is None:
                    raise RuntimeError("DuckDB no contiene metadatos de proyecto.")
                descriptor = ProjectDescriptor.from_metadata(
                    project,
                    unit_of_work.feeds.latest_metadata(),
                    self._opened_project.directory,
                )
            save_project_descriptor(self._opened_project.directory / "project.json", descriptor)
            self._opened_project.descriptor = descriptor
        except Exception as error:
            self._show_error(
                f"No se pudo actualizar el descriptor del proyecto: {error}",
                operation="synchronize_project_descriptor",
                exception=error,
            )

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
            feed = unit_of_work.feeds.latest_metadata()
            if feed is None:
                return PagedResult((), 0, page)
            scoped_filter = replace(report_filter, feed_id=feed.feed_id)
            return ValidationQueries(unit_of_work.validation).issues(scoped_filter, page)

    def _query_validation_files(self) -> tuple[str, ...]:
        if self._opened_project is None:
            return ()
        with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
            feed = unit_of_work.feeds.latest_metadata()
            if feed is None:
                return ()
            return ValidationQueries(unit_of_work.validation).files(feed_id=feed.feed_id)

    def _query_validation_summary(self) -> ValidationOverview | None:
        if self._opened_project is None:
            return None
        with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
            return FeedOverviewQueries(unit_of_work.overview).get().validation

    def _show_section(self, index: int) -> None:
        explorer_visible = index == 1
        validation_visible = index == 2
        export_visible = index == 3
        self._explore_tabs.setVisible(explorer_visible)
        self._validation.setVisible(validation_visible)
        self._exporter.setVisible(export_visible)
        self._overview.setVisible(not (explorer_visible or validation_visible or export_visible))
        self._operation_history.setVisible(
            not (explorer_visible or validation_visible or export_visible)
        )
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
        """Registra y ejecuta una exportación real de feed."""
        if self._opened_project is None:
            raise RuntimeError("Abra un proyecto antes de exportar.")
        database = self._opened_project.database
        project_id = getattr(getattr(self._opened_project, "descriptor", None), "project_id", None)
        if project_id is None:
            with DuckDbUnitOfWork(database) as unit_of_work:
                project = unit_of_work.projects.metadata()
                if project is None:
                    raise RuntimeError("El proyecto no contiene metadatos persistidos.")
                project_id = project.project_id
        with DuckDbUnitOfWork(database) as unit_of_work:
            feed = unit_of_work.feeds.latest_metadata()
            if feed is None:
                raise RuntimeError("El proyecto no contiene un feed importado.")
            feed_id = feed.feed_id
        try:
            result = cast(
                ExportResult,
                FeedExportLifecycle().execute(
                    database,
                    project_id,
                    feed_id,
                    request.format.value,
                    lambda _operation_id: self._write_feed_export(request, feed_id, is_cancelled),
                ),
            )
        finally:
            self._refresh_operation_history()
        return result

    def _export_feed_from_ui(
        self, request: ExportRequest, is_cancelled: Callable[[], bool]
    ) -> ExportResult:
        """Prepara el destino sugerido antes de delegar en el compositor real."""
        prepared_request = self._prepare_export_request(request)
        result = self._export_feed(prepared_request, is_cancelled)
        self._remember_directory(DirectoryKind.EXPORTS, prepared_request.destination.parent)
        return result

    def _prepare_export_request(self, request: ExportRequest) -> ExportRequest:
        """Crea lazymente el destino predeterminado sin alterar destinos elegidos."""

        destination = request.destination
        default_directory = self._directory_preferences.initial_directory(DirectoryKind.EXPORTS)
        if destination.parent == default_directory and not destination.parent.is_dir():
            prepared = self._prepare_directory(DirectoryKind.EXPORTS)
            if prepared != destination.parent:
                destination = prepared / destination.name
        if destination == request.destination:
            return request
        return replace(request, destination=destination, overwrite=destination.exists())

    def _write_feed_export(
        self, request: ExportRequest, feed_id: str, is_cancelled: Callable[[], bool]
    ) -> ExportResult:
        """Compone exportadores sin mezclar filesystem y transacción del ledger."""
        if self._opened_project is None:
            raise RuntimeError("Abra un proyecto antes de exportar.")
        database = self._opened_project.database
        selection = SubsetSelection(
            request.route_ids,
            request.trip_ids or None,
            request.service_ids or None,
        )
        with DuckDbUnitOfWork(database) as unit_of_work:
            connection = unit_of_work._connection
            if request.format is ExportFormat.JSON:
                manifest = JsonBundleExporter().write(
                    connection,
                    request.destination,
                    feed_id=feed_id,
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
                ("Los opcionales no soportados o sin registros relevantes se han omitido.",),
                "GTFS Schedule validado localmente",
            )

    @staticmethod
    def _mini_gtfs_tables(
        connection: DatabaseConnection, specification: ScheduleSpec, subset: CoreSubset
    ) -> tuple[MiniGtfsTable, ...]:
        filters = (
            (
                "agency.txt",
                "gtfs_agency",
                "agency_id",
                subset.agency_ids,
                "agency_id, source_row",
            ),
            (
                "routes.txt",
                "gtfs_routes",
                "route_id",
                subset.route_ids,
                "route_id, source_row",
            ),
            (
                "trips.txt",
                "gtfs_trips",
                "trip_id",
                subset.trip_ids,
                "trip_id, source_row",
            ),
            (
                "stops.txt",
                "gtfs_stops",
                "stop_id",
                subset.stop_ids,
                "stop_id, source_row",
            ),
            (
                "stop_times.txt",
                "gtfs_stop_times",
                "trip_id",
                subset.trip_ids,
                "trip_id, stop_sequence NULLS LAST, source_row",
            ),
            (
                "calendar.txt",
                "gtfs_calendar",
                "service_id",
                subset.calendar_service_ids,
                "service_id, source_row",
            ),
            (
                "calendar_dates.txt",
                "gtfs_calendar_dates",
                "service_id",
                subset.calendar_date_service_ids,
                "service_id, date NULLS LAST, exception_type NULLS LAST, source_row",
            ),
        )
        tables: list[MiniGtfsTable] = []
        for filename, table, column, values, order_by in filters:
            if not values:
                continue
            materialized = MainWindow._read_mini_gtfs_table(
                connection,
                specification,
                filename,
                table,
                f"{column} IN ({','.join('?' for _ in values)})",
                sorted(values),
                order_by,
            )
            if materialized is None:
                tables.append(
                    MiniGtfsTable(filename, tuple(specification.files[filename].fields), ())
                )
            else:
                tables.append(materialized)

        optional_queries: tuple[tuple[str, str, str, Sequence[object], str], ...] = (
            (
                "frequencies.txt",
                "gtfs_frequencies",
                f"trip_id IN ({','.join('?' for _ in subset.trip_ids)})",
                list(sorted(subset.trip_ids)),
                "trip_id, start_time_service_seconds NULLS LAST, source_row",
            ),
            (
                "transfers.txt",
                "gtfs_transfers",
                *_closed_reference_query(subset, "transfers"),
                "from_stop_id NULLS LAST, to_stop_id NULLS LAST, source_row",
            ),
            ("feed_info.txt", "gtfs_feed_info", "TRUE", (), "source_row"),
            (
                "attributions.txt",
                "gtfs_attributions",
                *_closed_reference_query(subset, "attributions"),
                "attribution_id NULLS LAST, source_row",
            ),
        )
        for filename, table, predicate, parameters, order_by in optional_queries:
            materialized = MainWindow._read_mini_gtfs_table(
                connection,
                specification,
                filename,
                table,
                predicate,
                parameters,
                order_by,
            )
            if materialized is not None:
                tables.append(materialized)

        # ``shape_id`` es opcional en trips.txt, pero si se conserva su valor
        # también debe conservarse la geometría referenciada; de lo contrario
        # la reimportación formal rechaza el Mini-GTFS resultante.
        if subset.trip_ids:
            shapes = MainWindow._read_mini_gtfs_table(
                connection,
                specification,
                "shapes.txt",
                "gtfs_shapes",
                "shape_id IN (SELECT DISTINCT shape_id FROM gtfs_trips WHERE trip_id IN ("
                + ",".join("?" for _ in subset.trip_ids)
                + ") AND shape_id IS NOT NULL)",
                sorted(subset.trip_ids),
                "shape_id, shape_pt_sequence NULLS LAST, source_row",
            )
            if shapes is not None:
                tables.append(shapes)
        return tuple(tables)

    @staticmethod
    def _read_mini_gtfs_table(
        connection: DatabaseConnection,
        specification: ScheduleSpec,
        filename: str,
        table: str,
        predicate: str,
        parameters: Sequence[object],
        order_by: str,
    ) -> MiniGtfsTable | None:
        rows = connection.execute(
            f"SELECT raw_values FROM {table} WHERE {predicate} ORDER BY {order_by}",
            parameters,
        ).fetchall()
        if not rows:
            return None
        headers = tuple(specification.files[filename].fields)
        return MiniGtfsTable(
            filename,
            headers,
            tuple(tuple(json.loads(row[0]).get(header) for header in headers) for row in rows),
        )

    def _show_validation(self) -> None:
        self._navigation.setCurrentRow(2)

    def _query_operations(
        self, operation_type: OperationType | None, status: OperationStatus | None
    ) -> PagedResult[Operation]:
        if self._opened_project is None:
            return PagedResult((), 0, PageRequest())
        project_id = getattr(getattr(self._opened_project, "descriptor", None), "project_id", None)
        with DuckDbUnitOfWork(self._opened_project.database) as unit_of_work:
            if project_id is None:
                metadata = unit_of_work.projects.metadata()
                if metadata is None:
                    return PagedResult((), 0, PageRequest())
                project_id = metadata.project_id
            return unit_of_work.operations.list_operations(
                project_id,
                PageRequest(limit=100),
                operation_type,
                status,
            )

    def _refresh_operation_history(self) -> None:
        if self._opened_project is None:
            self._operation_history.clear()
            return
        try:
            self._operation_history.refresh()
        except Exception as error:
            self._show_error(
                "No se pudo actualizar el historial de operaciones.",
                operation="refresh_operations_history",
                exception=error,
            )

    def _set_map_mode(self, _index: int = -1) -> None:
        value = self._map_mode_combo.currentData()
        if not isinstance(value, (MapMode, str)):
            return
        mode = normalize_map_mode(value)
        try:
            status = self._explorer.set_map_mode(mode)
        except (RuntimeError, ValueError) as error:
            self._map_policy_status.setText(self._explorer.map_status)
            self._show_error(
                f"No se pudo cambiar el modo de mapa: {error}",
                operation="set_map_mode",
                exception=error,
            )
            return
        self._map_policy_status.setText(status)

    def _select_map_package(self) -> None:
        start_directory = self._dialog_directory(DirectoryKind.PMTILES_IMPORT)
        directory = QFileDialog.getExistingDirectory(
            self, t("dialog.select_map_package_title"), str(start_directory)
        )
        if not directory:
            return
        try:
            package = self._offline_map_library.import_package(Path(directory))
            self._explorer.set_managed_map(self._offline_map_library, package)
        except (OSError, ValueError, RuntimeError) as error:
            self._map_package_status.setText("Paquete rechazado: se mantiene el fondo neutro.")
            self._map_policy_status.setText(self._explorer.map_status)
            self._show_error(
                f"No se pudo abrir el paquete de mapa: {error}",
                operation="select_map_package",
                exception=error,
            )
            return
        status = self._explorer.map_status
        self._map_package_status.setText(
            f"Paquete local instalado. {status} · Atribución: {package.attribution or '—'}"
        )
        self._remember_directory(DirectoryKind.PMTILES_IMPORT, Path(directory))
        self._refresh_offline_maps()
        self._map_policy_status.setText(status)

    def _import_pmtiles(self) -> None:
        start_directory = self._dialog_directory(DirectoryKind.PMTILES_IMPORT)
        source, _ = QFileDialog.getOpenFileName(
            self,
            t("dialog.import_pmtiles_title"),
            str(start_directory),
            filter=t("dialog.pmtiles_filter"),
        )
        if not source:
            return
        try:
            source_path = Path(source)
            package = self._offline_map_library.import_file(source_path)
            result = (
                "Mapa importado"
                if package.is_renderable
                else "PMTiles válido · estilo compatible no disponible"
            )
            self._map_package_status.setText(f"{result}: {package.name}")
            self._remember_file_directory(DirectoryKind.PMTILES_IMPORT, source_path)
            self._refresh_offline_maps()
            self._resolve_global_map()
        except (OSError, ValueError) as error:
            self._show_error(str(error), operation="import_pmtiles", exception=error)

    def _resolve_global_map(self) -> None:
        """Selecciona localmente el mejor PMTiles global; nunca bloquea el proyecto."""
        if self._opened_project is None:
            return
        try:
            library = self._offline_map_library
            with self._opened_project.database.connection() as connection:
                coverage = project_map_coverage(connection)
            package = resolve_best_map(coverage, library.installed_maps())
            if package is None:
                if coverage.bounds is not None:
                    self._map_package_status.setText(
                        "No hay mapa offline para la zona de este proyecto."
                    )
                return
            self._explorer.set_managed_map(library, package)
            self._map_package_status.setText(f"Mapa global seleccionado: {package.name}")
            self._map_policy_status.setText(self._explorer.map_status)
        except Exception as error:
            logging.getLogger(__name__).warning("No se pudo resolver el mapa global: %s", error)

    def _refresh_offline_maps(self) -> None:
        """Panel informativo: el índice no expone rutas absolutas."""
        library = self._offline_map_library
        try:
            maps = library.installed_maps()
        except ValueError:
            maps = ()
        self._offline_maps.setRowCount(len(maps))
        for row, item in enumerate(maps):
            coverage = "—"
            if self._opened_project is not None:
                try:
                    with self._opened_project.database.connection() as connection:
                        coverage = project_map_coverage(connection).source or "Disponible"
                except Exception:
                    coverage = "—"
            values = (
                item.name,
                item.tile_type.value,
                coverage,
                f"{item.size / (1024 * 1024):.1f} MB",
                "Listo" if item.is_renderable else "Sin estilo compatible",
                " · ".join(x for x in (item.source, item.version) if x) or "—",
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, (item.package_id, item.version))
                self._offline_maps.setItem(row, column, cell)

    def _remove_selected_offline_map(self) -> None:
        row = self._offline_maps.currentRow()
        if row < 0 or (cell := self._offline_maps.item(row, 0)) is None:
            return
        identity = cell.data(Qt.ItemDataRole.UserRole)
        if not isinstance(identity, tuple) or len(identity) != 2:
            return
        if (
            QMessageBox.question(
                self,
                t("dialog.remove_map_title"),
                t("dialog.remove_map_message"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            is not QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self._offline_map_library.remove(identity[0], identity[1])
            self._explorer.clear_managed_map()
            self._refresh_offline_maps()
            self._resolve_global_map()
            self._map_package_status.setText("Mapa offline eliminado.")
            self._map_policy_status.setText(self._explorer.map_status)
        except (OSError, ValueError) as error:
            self._show_error(str(error), operation="remove_offline_map", exception=error)

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

    def _show_about(self) -> None:
        AboutDialog(self._application_paths.application_data_directory, parent=self).exec()

    def _export_validation_report(
        self, batch_id: str, report_filter: ValidationIssueFilter
    ) -> None:
        start_directory = self._prepare_directory(DirectoryKind.EXPORTS)
        destination, selected_filter = QFileDialog.getSaveFileName(
            self,
            t("dialog.validation_report_title"),
            str(start_directory / "informe-validacion.html"),
            t("dialog.validation_report_filter"),
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
                self,
                t("dialog.overwrite_report_title"),
                t("dialog.overwrite_report_message", filename=path.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
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
            self._show_error(
                f"No se pudo exportar el informe: {error}",
                operation="export_validation_report",
                exception=error,
            )
            return
        self._remember_file_directory(DirectoryKind.EXPORTS, path)
        QMessageBox.information(
            self,
            t("dialog.report_exported_title"),
            t("dialog.report_exported_message", filename=path.name),
            QMessageBox.StandardButton.Ok,
        )


def run_window(
    *,
    application_paths: ApplicationPaths | None = None,
    logger: logging.Logger | None = None,
    logs_directory: Path | None = None,
    debug: bool = False,
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(IDENTITY.name)
    app.setApplicationVersion(IDENTITY.version)
    StartupIntroDialog().exec()
    window = MainWindow(
        application_paths=application_paths,
        logger=logger,
        logs_directory=logs_directory,
        debug=debug,
    )
    window.show()
    return app.exec()
