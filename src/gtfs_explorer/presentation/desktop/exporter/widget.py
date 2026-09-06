"""Asistente de exportación: contrato de UI y ayudas seguras por formato."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.domain.exporting import ExportManifest
from gtfs_explorer.presentation.desktop.i18n import t

from .naming import normalize_export_destination, sanitize_export_component, suggest_export_filename


class ExportFormat(StrEnum):
    JSON = "json"
    GEOJSON = "geojson"
    CSV = "csv"
    MINI_GTFS = "mini_gtfs"
    COMPLETE_GTFS = "complete_gtfs"
    FULL_GTFS = "complete_gtfs"
    NEW_GTFS_VERSION = "new_gtfs_version"
    KML = "kml"
    KMZ = "kmz"


@dataclass(frozen=True)
class ExportRequest:
    """Selección explícita que la capa de composición ejecutará localmente."""

    format: ExportFormat
    destination: Path
    route_ids: frozenset[str] = frozenset()
    trip_ids: frozenset[str] = frozenset()
    service_ids: frozenset[str] = frozenset()
    include_bbox: bool = False
    spreadsheet_safe: bool = False
    overwrite: bool = False
    version_id: str | None = None
    kml_profile: str | None = None

    @property
    def is_pack(self) -> bool:
        """Indica que la selección agrupa más de una ruta o servicio."""
        return len(self.route_ids) > 1 or len(self.service_ids) > 1


@dataclass(frozen=True)
class ExportPreview:
    """Dependencias que se incluirán; nunca promete que una salida sea oficial."""

    dependencies: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExportRouteOption:
    route_id: str
    label: str


@dataclass(frozen=True)
class ExportServiceOption:
    service_id: str
    label: str
    route_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ExportResult:
    manifest: ExportManifest
    warnings: tuple[str, ...] = ()
    classification: str = "derivada"


@dataclass(frozen=True)
class ExportFailure:
    """Diagnóstico interno del último fallo, sin mostrar detalles al usuario."""

    exception_type: str
    message: str


Previewer = Callable[[ExportRequest], ExportPreview]
Executor = Callable[[ExportRequest, Callable[[], bool]], ExportResult]


class _ExportSignals(QObject):
    succeeded = Signal(int, object, object)
    failed = Signal(int, object)
    cancelled = Signal(int)


class _ExportJob(QRunnable):
    """Ejecuta el exportador fuera del hilo Qt y solo emite un resultado."""

    def __init__(
        self,
        generation: int,
        executor: Executor,
        request: ExportRequest,
        is_cancelled: Callable[[], bool],
        signals: _ExportSignals,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.executor = executor
        self.request = request
        self.is_cancelled = is_cancelled
        self.signals = signals

    def run(self) -> None:
        try:
            result = self.executor(self.request, self.is_cancelled)
        except Exception as error:
            if self.is_cancelled():
                self.signals.cancelled.emit(self.generation)
            else:
                self.signals.failed.emit(self.generation, error)
            return
        if self.is_cancelled():
            self.signals.cancelled.emit(self.generation)
        else:
            self.signals.succeeded.emit(self.generation, self.request, result)


class ExportAssistantWidget(QWidget):
    """Recoge una exportación de alcance acotado y comunica sus límites.

    La ejecución se inyecta para que la presentación no conozca DuckDB ni las
    reglas de cierre. El cancelador se consulta de forma cooperativa por la
    capa que materializa cada formato.
    """

    def __init__(
        self,
        previewer: Previewer | None = None,
        executor: Executor | None = None,
        parent: QWidget | None = None,
        *,
        default_directory_resolver: Callable[[], Path] | None = None,
        prepare_default_directory: Callable[[], Path] | None = None,
        on_destination_directory_used: Callable[[Path], None] | None = None,
        on_terminal: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._previewer = previewer or _default_preview
        self._executor = executor
        self._default_directory_resolver = default_directory_resolver
        self._prepare_default_directory = prepare_default_directory
        self._on_destination_directory_used = on_destination_directory_used
        self._on_terminal = on_terminal
        self._cancelled = False
        self._cancel_token: Event | None = None
        self._export_generation = 0
        self._active_export_generation: int | None = None
        self._export_jobs: dict[int, tuple[_ExportJob, _ExportSignals]] = {}
        self._last_failure: ExportFailure | None = None
        self._suggested_destination_text = ""
        self._route_options: tuple[ExportRouteOption, ...] = ()
        self._service_options: tuple[ExportServiceOption, ...] = ()
        self._build()
        self._refresh()

    def set_executor(self, executor: Executor | None) -> None:
        if executor is None:
            self._request_cancel()
        self._executor = executor
        self._refresh()

    def clear(self) -> None:
        """Elimina toda selección y destino dependientes del proyecto actual."""
        self._request_cancel()
        self._active_export_generation = None
        self._cancelled = False
        self._cancel_token = None
        self._suggested_destination_text = ""
        self._format.blockSignals(True)
        self._format.setCurrentIndex(0)
        self._format.blockSignals(False)
        for editor in (self._routes, self._trips, self._services):
            editor.clear()
        self.set_inventory((), ())
        self._destination.clear()
        self._version.clear()
        self._profile.setCurrentIndex(0)
        self._bbox.setChecked(False)
        self._spreadsheet_safe.setChecked(False)
        self._cancel.setEnabled(False)
        self._refresh()

    def request(self) -> ExportRequest:
        format_ = ExportFormat(self._format.currentData())
        destination = _effective_destination(
            format_,
            Path(self._destination.text()),
            self._spreadsheet_safe.isChecked(),
            default_directory=self._default_directory(),
        )
        return ExportRequest(
            format_,
            destination,
            route_ids=(
                self._selected_ids(self._route_inventory)
                or _identifiers(self._routes.toPlainText())
            ),
            trip_ids=_identifiers(self._trips.toPlainText()),
            service_ids=(
                self._selected_ids(self._service_inventory)
                or _identifiers(self._services.toPlainText())
            ),
            include_bbox=self._bbox.isChecked(),
            spreadsheet_safe=self._spreadsheet_safe.isChecked(),
            overwrite=destination.exists(),
            version_id=(
                self._version.text().strip() or None
                if format_ is ExportFormat.NEW_GTFS_VERSION
                else None
            ),
            kml_profile=(
                str(self._profile.currentData())
                if format_ in {ExportFormat.KML, ExportFormat.KMZ}
                else None
            ),
        )

    def set_inventory(
        self,
        routes: tuple[ExportRouteOption, ...],
        services: tuple[ExportServiceOption, ...],
    ) -> None:
        """Carga inventario GTFS; la UI selecciona IDs sin exigir que se conozcan."""
        self._route_options, self._service_options = routes, services
        self._populate_inventory(self._route_inventory, routes, self._route_search.text())
        self._refresh_service_inventory()

    @staticmethod
    def _selected_ids(widget: QListWidget) -> frozenset[str]:
        return frozenset(
            str(widget.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(widget.count())
            if widget.item(index).checkState() == Qt.CheckState.Checked
        )

    def _populate_inventory(
        self, widget: QListWidget, options: tuple[object, ...], query: str = ""
    ) -> None:
        selected = self._selected_ids(widget)
        widget.blockSignals(True)
        widget.clear()
        needle = query.casefold().strip()
        for option in options:
            identifier_value = getattr(option, "route_id", None)
            if identifier_value is None:
                identifier_value = getattr(option, "service_id")
            identifier = str(identifier_value)
            label = str(getattr(option, "label"))
            if needle and needle not in f"{label} {identifier}".casefold():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, identifier)
            item.setCheckState(
                Qt.CheckState.Checked if identifier in selected else Qt.CheckState.Unchecked
            )
            widget.addItem(item)
        widget.blockSignals(False)

    def _refresh_service_inventory(self) -> None:
        selected_routes = self._selected_ids(self._route_inventory)
        options = tuple(
            option
            for option in self._service_options
            if not selected_routes or not option.route_ids or option.route_ids & selected_routes
        )
        self._populate_inventory(self._service_inventory, options)

    @staticmethod
    def _set_all(widget: QListWidget, checked: bool) -> None:
        for index in range(widget.count()):
            widget.item(index).setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        description = QLabel(t("export.introduction"))
        self._description = description
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self._format = QComboBox()
        self._format.setObjectName("exportFormat")
        self._format.setAccessibleName(t("export.format"))
        self._format.addItem(t("export.format_json"), ExportFormat.JSON.value)
        self._format.addItem(t("export.format_geojson"), ExportFormat.GEOJSON.value)
        self._format.addItem(t("export.format_csv"), ExportFormat.CSV.value)
        self._format.addItem(t("export.format_mini_gtfs"), ExportFormat.MINI_GTFS.value)
        self._format.addItem(t("export.format_complete_gtfs"), ExportFormat.COMPLETE_GTFS.value)
        self._format.addItem(t("export.format_new_gtfs"), ExportFormat.NEW_GTFS_VERSION.value)
        self._format.addItem(t("export.format_kml"), ExportFormat.KML.value)
        self._format.addItem(t("export.format_kmz"), ExportFormat.KMZ.value)
        format_label = QLabel(t("export.format_label"))
        self._format_label = format_label
        format_label.setBuddy(self._format)
        form.addRow(format_label, self._format)
        self._routes = _identifiers_editor("exportRoutes")
        self._trips = _identifiers_editor("exportTrips")
        self._services = _identifiers_editor("exportServices")
        self._routes.setAccessibleName(t("export.routes"))
        self._trips.setAccessibleName(t("export.trips"))
        self._services.setAccessibleName(t("export.services"))
        self._route_search = QLineEdit()
        self._route_search.setObjectName("exportRouteSearch")
        self._route_search.setPlaceholderText(t("export.route_search"))
        self._route_inventory = QListWidget()
        self._route_inventory.setObjectName("exportRouteInventory")
        self._route_inventory.setAccessibleName(t("export.routes"))
        self._route_inventory.setMaximumHeight(130)
        route_controls = QHBoxLayout()
        all_routes = QPushButton(t("export.select_all_routes"))
        self._all_routes_button = all_routes
        clear_routes = QPushButton(t("export.clear_routes"))
        self._clear_routes_button = clear_routes
        route_controls.addWidget(all_routes)
        route_controls.addWidget(clear_routes)
        route_box = QVBoxLayout()
        route_box.addWidget(self._route_search)
        route_box.addWidget(self._route_inventory)
        route_box.addLayout(route_controls)
        self._routes_label = QLabel(t("export.routes_label"))
        form.addRow(self._routes_label, route_box)
        self._service_inventory = QListWidget()
        self._service_inventory.setObjectName("exportServiceInventory")
        self._service_inventory.setAccessibleName(t("export.services"))
        self._service_inventory.setMaximumHeight(110)
        service_controls = QHBoxLayout()
        all_services = QPushButton(t("export.select_all_services"))
        self._all_services_button = all_services
        clear_services = QPushButton(t("export.clear_services"))
        self._clear_services_button = clear_services
        service_controls.addWidget(all_services)
        service_controls.addWidget(clear_services)
        service_box = QVBoxLayout()
        service_box.addWidget(self._service_inventory)
        service_box.addLayout(service_controls)
        self._services_label = QLabel(t("export.services_label"))
        form.addRow(self._services_label, service_box)
        # Los viajes siguen disponibles como filtro avanzado, no como requisito normal.
        for label_text, editor in ((t("export.trips_advanced_label"), self._trips),):
            label = QLabel(label_text)
            self._trips_label = label
            label.setBuddy(editor)
        form.addRow(label, editor)
        self._version = QLineEdit()
        self._version.setObjectName("exportVersionId")
        self._version.setAccessibleName(t("export.version_id"))
        self._version.setPlaceholderText(t("export.version_placeholder"))
        self._version_label = QLabel(t("export.version_label"))
        self._version_label.setBuddy(self._version)
        form.addRow(self._version_label, self._version)
        self._profile = QComboBox()
        self._profile.setObjectName("exportKmlProfile")
        self._profile.setAccessibleName(t("export.kml_profile"))
        self._profile.addItem(t("export.profile_standard"), "STANDARD_KML")
        self._profile.addItem(t("export.profile_google_earth"), "GOOGLE_EARTH")
        self._profile.addItem(t("export.profile_google_maps"), "GOOGLE_MY_MAPS")
        self._profile_label = QLabel(t("export.kml_profile_label"))
        self._profile_label.setBuddy(self._profile)
        form.addRow(self._profile_label, self._profile)
        all_routes.clicked.connect(lambda: self._set_all(self._route_inventory, True))
        clear_routes.clicked.connect(lambda: self._set_all(self._route_inventory, False))
        all_services.clicked.connect(lambda: self._set_all(self._service_inventory, True))
        clear_services.clicked.connect(lambda: self._set_all(self._service_inventory, False))
        self._route_search.textChanged.connect(
            lambda value: self._populate_inventory(
                self._route_inventory, self._route_options, value
            )
        )
        destination_row = QHBoxLayout()
        self._destination = QLineEdit()
        self._destination.setObjectName("exportDestination")
        self._destination.setAccessibleName(t("export.destination"))
        browse = QPushButton(t("export.browse"))
        self._browse_button = browse
        browse.setAccessibleName(t("export.browse"))
        browse.setAccessibleDescription(t("export.browse_description"))
        browse.setToolTip(t("export.browse"))
        browse.clicked.connect(self._choose_destination)
        destination_row.addWidget(self._destination)
        destination_row.addWidget(browse)
        destination_label = QLabel(t("export.destination_label"))
        self._destination_label = destination_label
        destination_label.setBuddy(self._destination)
        form.addRow(destination_label, destination_row)
        self._bbox = QCheckBox(t("export.include_bbox"))
        self._bbox.setObjectName("exportBbox")
        self._spreadsheet_safe = QCheckBox(t("export.spreadsheet_safe"))
        self._spreadsheet_safe.setObjectName("exportSpreadsheetSafe")
        form.addRow(self._bbox)
        form.addRow(self._spreadsheet_safe)
        layout.addLayout(form)
        self._format_help = QLabel()
        self._format_help.setWordWrap(True)
        self._format_help.setObjectName("exportFormatHelp")
        layout.addWidget(self._format_help)
        self._preview = QLabel()
        self._preview.setWordWrap(True)
        self._preview.setObjectName("exportDependencyPreview")
        self._preview.setAccessibleName(t("export.preview"))
        layout.addWidget(self._preview)
        buttons = QHBoxLayout()
        self._export = QPushButton(t("export.start"))
        self._export.setObjectName("exportStart")
        self._export.setAccessibleName(t("export.start"))
        self._export.setToolTip(t("export.start"))
        self._cancel = QPushButton(t("export.cancel"))
        self._cancel.setObjectName("exportCancel")
        self._cancel.setAccessibleName(t("export.cancel"))
        self._cancel.setToolTip(t("export.cancel"))
        self._cancel.setEnabled(False)
        self._export.clicked.connect(self._execute)
        self._cancel.clicked.connect(self._request_cancel)
        buttons.addWidget(self._export)
        buttons.addWidget(self._cancel)
        layout.addLayout(buttons)
        self.setTabOrder(self._format, self._routes)
        self.setTabOrder(self._routes, self._trips)
        self.setTabOrder(self._trips, self._services)
        self.setTabOrder(self._services, self._destination)
        self.setTabOrder(self._destination, browse)
        self.setTabOrder(browse, self._bbox)
        self.setTabOrder(self._bbox, self._spreadsheet_safe)
        self.setTabOrder(self._spreadsheet_safe, self._export)
        self.setTabOrder(self._export, self._cancel)
        for widget in (
            self._format,
            self._routes,
            self._trips,
            self._services,
            self._destination,
            self._version,
        ):
            signal = (
                widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.textChanged
            )
            signal.connect(self._refresh)
        self._route_inventory.itemChanged.connect(self._refresh_service_inventory)
        self._route_inventory.itemChanged.connect(self._refresh)
        self._service_inventory.itemChanged.connect(self._refresh)
        self._bbox.toggled.connect(self._refresh)
        self._spreadsheet_safe.toggled.connect(self._refresh)

    def retranslate_ui(self) -> None:
        """Actualiza etiquetas del asistente sin perder la selección de exportación."""
        self._description.setText(t("export.introduction"))
        self._format_label.setText(t("export.format_label"))
        for index, key in enumerate(
            (
                "export.format_json",
                "export.format_geojson",
                "export.format_csv",
                "export.format_mini_gtfs",
                "export.format_complete_gtfs",
                "export.format_new_gtfs",
                "export.format_kml",
                "export.format_kmz",
            )
        ):
            if index < self._format.count():
                self._format.setItemText(index, t(key))
        self._routes.setAccessibleName(t("export.routes"))
        self._trips.setAccessibleName(t("export.trips"))
        self._services.setAccessibleName(t("export.services"))
        self._route_search.setPlaceholderText(t("export.route_search"))
        self._all_routes_button.setText(t("export.select_all_routes"))
        self._clear_routes_button.setText(t("export.clear_routes"))
        self._all_services_button.setText(t("export.select_all_services"))
        self._clear_services_button.setText(t("export.clear_services"))
        self._routes_label.setText(t("export.routes_label"))
        self._trips_label.setText(t("export.trips_advanced_label"))
        self._services_label.setText(t("export.services_label"))
        self._version.setAccessibleName(t("export.version_id"))
        self._version.setPlaceholderText(t("export.version_placeholder"))
        self._version_label.setText(t("export.version_label"))
        self._profile.setAccessibleName(t("export.kml_profile"))
        for index, key in enumerate(
            (
                "export.profile_standard",
                "export.profile_google_earth",
                "export.profile_google_maps",
            )
        ):
            if index < self._profile.count():
                self._profile.setItemText(index, t(key))
        self._profile_label.setText(t("export.kml_profile_label"))
        self._destination.setAccessibleName(t("export.destination"))
        self._browse_button.setText(t("export.browse"))
        self._browse_button.setAccessibleName(t("export.browse"))
        self._browse_button.setAccessibleDescription(t("export.browse_description"))
        self._browse_button.setToolTip(t("export.browse"))
        self._destination_label.setText(t("export.destination_label"))
        self._bbox.setText(t("export.include_bbox"))
        self._spreadsheet_safe.setText(t("export.spreadsheet_safe"))
        self._preview.setAccessibleName(t("export.preview"))
        self._export.setText(t("export.start"))
        self._export.setAccessibleName(t("export.start"))
        self._export.setToolTip(t("export.start"))
        self._cancel.setText(t("export.cancel"))
        self._cancel.setAccessibleName(t("export.cancel"))
        self._cancel.setToolTip(t("export.cancel"))
        self._refresh()

    def _refresh(self) -> None:
        format_ = ExportFormat(self._format.currentData())
        route_ids = self._selected_ids(self._route_inventory) or _identifiers(
            self._routes.toPlainText()
        )
        trip_ids = _identifiers(self._trips.toPlainText())
        service_ids = self._selected_ids(self._service_inventory) or _identifiers(
            self._services.toPlainText()
        )
        # Todas las salidas se acotan por rutas; incluso el CSV es una vista
        # compatible de las rutas seleccionadas, no una exportación implícita
        # de todo el feed.
        needs_routes = format_ not in {
            ExportFormat.COMPLETE_GTFS,
            ExportFormat.NEW_GTFS_VERSION,
        }
        self._routes.setEnabled(needs_routes)
        self._trips.setEnabled(needs_routes)
        self._services.setEnabled(needs_routes)
        self._bbox.setEnabled(format_ is ExportFormat.GEOJSON)
        self._spreadsheet_safe.setEnabled(format_ is ExportFormat.CSV)
        self._version.setEnabled(format_ is ExportFormat.NEW_GTFS_VERSION)
        self._profile.setEnabled(format_ in {ExportFormat.KML, ExportFormat.KMZ})
        if format_ is not ExportFormat.NEW_GTFS_VERSION:
            self._version.clear()
        if format_ not in {ExportFormat.KML, ExportFormat.KMZ}:
            self._profile.setCurrentIndex(0)
        if format_ is not ExportFormat.GEOJSON:
            self._bbox.setChecked(False)
        if format_ is not ExportFormat.CSV:
            self._spreadsheet_safe.setChecked(False)
        proposed_name = suggest_export_filename(
            format_,
            route_ids=route_ids,
            trip_ids=trip_ids,
            service_ids=service_ids,
            spreadsheet_safe=self._spreadsheet_safe.isChecked(),
        )
        has_required_scope = bool(route_ids) or format_ in {
            ExportFormat.COMPLETE_GTFS,
            ExportFormat.NEW_GTFS_VERSION,
        }
        self._sync_proposed_destination(proposed_name if has_required_scope else "")
        self._format_help.setText(
            _format_help(
                format_,
                route_ids=route_ids,
                trip_ids=trip_ids,
                service_ids=service_ids,
                spreadsheet_safe=self._spreadsheet_safe.isChecked(),
            )
        )
        request = self.request()
        if needs_routes and not request.route_ids:
            self._preview.setText(t("export.preview_missing_routes"))
            self._export.setEnabled(False)
            return
        if format_ is ExportFormat.NEW_GTFS_VERSION and not request.version_id:
            self._preview.setText(t("export.preview_missing_version"))
            self._export.setEnabled(False)
            return
        if not request.destination.name:
            self._preview.setText(t("export.preview_missing_destination"))
            self._export.setEnabled(False)
            return
        preview = self._previewer(request)
        selection_summary = t(
            "export.selection_summary",
            routes=len(request.route_ids),
            services=len(request.service_ids),
            trips=len(request.trip_ids),
        )
        lines = [
            selection_summary,
            t(
                "export.preview_dependencies",
                dependencies=", ".join(preview.dependencies) or t("export.preview_no_dependencies"),
            ),
        ]
        if request.is_pack:
            lines.insert(1, t("export.pack_title"))
        lines.extend(t("export.preview_warning", warning=warning) for warning in preview.warnings)
        if request.destination.exists():
            lines.append(t("export.preview_existing_destination"))
        self._preview.setText("\n".join(lines))
        self._export.setEnabled(self._executor is not None)

    def _sync_proposed_destination(self, proposed_name: str) -> None:
        current = self._destination.text()
        if not proposed_name:
            if current == self._suggested_destination_text:
                self._destination.clear()
            self._suggested_destination_text = ""
            return
        if current and current != self._suggested_destination_text:
            # Un nombre escrito manualmente no se sustituye al cambiar el
            # formato o la selección; la ayuda sigue mostrando la propuesta.
            self._suggested_destination_text = ""
            return
        self._suggested_destination_text = proposed_name
        if current != proposed_name:
            self._destination.setText(proposed_name)

    def _choose_destination(self) -> None:
        directory = (
            self._prepare_default_directory()
            if self._prepare_default_directory is not None
            else self._default_directory()
        )
        current_name = Path(self._destination.text()).name or "gtfs-export.json"
        initial = str(directory / current_name) if directory is not None else current_name
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("dialog.export_title"),
            initial,
            _format_filter(ExportFormat(self._format.currentData())),
        )
        if path:
            selected = Path(path)
            self._destination.setText(str(selected))
            if self._on_destination_directory_used is not None:
                self._on_destination_directory_used(selected.parent)

    def _execute(self) -> None:
        if self._executor is None or self._active_export_generation is not None:
            return
        request = self.request()
        if (
            request.destination.exists()
            and QMessageBox.question(
                self,
                t("dialog.overwrite_export_title"),
                t("dialog.overwrite_export_message", filename=request.destination.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._cancelled = False
        cancel_token = Event()
        self._cancel_token = cancel_token
        self._export_generation += 1
        generation = self._export_generation
        self._active_export_generation = generation
        self._export.setEnabled(False)
        self._cancel.setEnabled(True)
        signals = _ExportSignals(self)
        signals.succeeded.connect(self._export_succeeded)
        signals.failed.connect(self._export_failed)
        signals.cancelled.connect(self._export_cancelled)
        job = _ExportJob(generation, self._executor, request, cancel_token.is_set, signals)
        # QThreadPool posee el QRunnable nativo, pero esta referencia conserva
        # también sus callbacks Python hasta recibir el único resultado terminal.
        self._export_jobs[generation] = (job, signals)
        QThreadPool.globalInstance().start(job)

    def _finish_export(self, generation: int) -> bool:
        self._export_jobs.pop(generation, None)
        if generation != self._active_export_generation:
            return False
        self._active_export_generation = None
        self._cancel_token = None
        self._cancel.setEnabled(False)
        self._refresh()
        if self._on_terminal is not None:
            self._on_terminal()
        return True

    def _export_succeeded(self, generation: int, request: object, result: object) -> None:
        if not self._finish_export(generation):
            return
        assert isinstance(request, ExportRequest)
        assert isinstance(result, ExportResult)
        warnings = "\n".join(
            t("export.preview_warning", warning=item) for item in result.warnings
        ) or t("export.no_warnings")
        self._show_export_completed(request.destination, result, warnings)

    def _export_failed(self, generation: int, error: object) -> None:
        if not self._finish_export(generation):
            return
        assert isinstance(error, Exception)
        self._last_failure = ExportFailure(type(error).__name__, str(error))
        QMessageBox.critical(
            self,
            t("dialog.export_error_title"),
            t("dialog.export_error_message"),
            QMessageBox.StandardButton.Ok,
        )

    def _export_cancelled(self, generation: int) -> None:
        if not self._finish_export(generation):
            return
        # La cancelación cooperativa no es un éxito ni expone salida parcial.
        self._preview.setText("Exportación cancelada.")

    def closeEvent(self, event: object) -> None:  # noqa: N802 - API Qt
        self._request_cancel()
        super().closeEvent(event)  # type: ignore[arg-type]

    def _request_cancel(self) -> None:
        if self._active_export_generation is None:
            self._cancel.setEnabled(False)
            return
        self._cancelled = True
        if self._cancel_token is not None:
            self._cancel_token.set()
        self._cancel.setEnabled(False)

    def _show_export_completed(
        self, destination: Path, result: ExportResult, warnings: str
    ) -> None:
        """Muestra el artefacto publicado y deja continuar hacia la reimportación."""
        destination = destination.resolve()
        dialog = QMessageBox(self)
        dialog.setWindowTitle(t("dialog.export_completed_title"))
        dialog.setText(
            t(
                "dialog.export_completed_message",
                classification=result.classification,
                filename=result.manifest.artifact_name,
                destination=destination,
                sha256=result.manifest.sha256,
                warnings=warnings,
            )
        )
        open_folder = dialog.addButton(
            t("dialog.export_open_folder_action"), QMessageBox.ButtonRole.ActionRole
        )
        copy_path = dialog.addButton(
            t("dialog.export_copy_path_action"), QMessageBox.ButtonRole.ActionRole
        )
        accept_button = dialog.addButton(QMessageBox.StandardButton.Ok)
        accept_button.setText(t("dialog.accept"))

        open_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(destination.parent)))
        )
        copy_path.clicked.connect(lambda: QApplication.clipboard().setText(str(destination)))
        open_folder.setToolTip(t("dialog.export_open_folder_tooltip"))
        copy_path.setToolTip(t("dialog.export_copy_path_tooltip"))
        dialog.exec()

    def _default_directory(self) -> Path | None:
        if self._default_directory_resolver is None:
            return None
        return self._default_directory_resolver()


def _format_filter(format_: ExportFormat) -> str:
    return {
        ExportFormat.JSON: t("dialog.filter_json"),
        ExportFormat.GEOJSON: t("dialog.filter_geojson"),
        ExportFormat.CSV: t("dialog.filter_csv"),
        ExportFormat.MINI_GTFS: t("dialog.filter_gtfs"),
        ExportFormat.COMPLETE_GTFS: t("dialog.filter_gtfs"),
        ExportFormat.NEW_GTFS_VERSION: t("dialog.filter_gtfs"),
        ExportFormat.KML: t("dialog.filter_kml"),
        ExportFormat.KMZ: t("dialog.filter_kmz"),
    }[format_]


def _identifiers(value: str) -> frozenset[str]:
    return frozenset(line.strip() for line in value.splitlines() if line.strip())


def _identifiers_editor(name: str) -> QPlainTextEdit:
    editor = QPlainTextEdit()
    editor.setObjectName(name)
    editor.setMaximumHeight(58)
    return editor


def _format_help(
    format_: ExportFormat,
    *,
    route_ids: frozenset[str] = frozenset(),
    trip_ids: frozenset[str] = frozenset(),
    service_ids: frozenset[str] = frozenset(),
    spreadsheet_safe: bool = False,
) -> str:
    descriptions = {
        ExportFormat.JSON: t("export.help_json"),
        ExportFormat.GEOJSON: t("export.help_geojson"),
        ExportFormat.CSV: t(
            "export.help_csv",
            mode=t("export.mode_spreadsheet_safe" if spreadsheet_safe else "export.mode_faithful"),
        ),
        ExportFormat.MINI_GTFS: t("export.help_mini_gtfs"),
        ExportFormat.COMPLETE_GTFS: t("export.help_complete_gtfs"),
        ExportFormat.NEW_GTFS_VERSION: t("export.help_new_gtfs"),
        ExportFormat.KML: t("export.help_kml"),
        ExportFormat.KMZ: t("export.help_kmz"),
    }
    selection = _selection_context(route_ids, trip_ids, service_ids)
    proposed_name = suggest_export_filename(
        format_,
        route_ids=route_ids,
        trip_ids=trip_ids,
        service_ids=service_ids,
        spreadsheet_safe=spreadsheet_safe,
    )
    return t(
        "export.help_summary",
        description=descriptions[format_],
        selection=selection,
        pack=(
            t("export.pack_description")
            if len(route_ids) > 1 or len(service_ids) > 1
            else t("export.single_description")
        ),
        proposed_name=proposed_name,
    )


def _selection_context(
    route_ids: frozenset[str], trip_ids: frozenset[str], service_ids: frozenset[str]
) -> str:
    parts: list[str] = []
    for key, values in (
        ("export.selection_routes", route_ids),
        ("export.selection_trips", trip_ids),
        ("export.selection_services", service_ids),
    ):
        if values:
            safe_values = sorted(
                (sanitize_export_component(value, fallback="id") for value in values),
                key=lambda value: (value.casefold(), value),
            )
            visible = ", ".join(safe_values[:4])
            parts.append(t(key, values=visible))
            if len(safe_values) > 4:
                parts[-1] += t("export.selection_more", count=len(safe_values) - 4)
    return " · ".join(parts) if parts else t("export.selection_empty")


def _effective_destination(
    format_: ExportFormat,
    destination: Path,
    spreadsheet_safe: bool,
    *,
    default_directory: Path | None = None,
) -> Path:
    """Devuelve el artefacto real antes de comprobar overwrite."""
    normalized = normalize_export_destination(format_, destination, spreadsheet_safe)
    if (
        default_directory is not None
        and normalized.name not in {"", ".", ".."}
        and not normalized.is_absolute()
    ):
        normalized = default_directory / normalized
    return normalized


def _default_preview(request: ExportRequest) -> ExportPreview:
    if request.format is ExportFormat.CSV:
        return ExportPreview(("cabecera y filas de la vista seleccionada",))
    dependencies = ("rutas", "viajes", "paradas", "servicios")
    if request.format is ExportFormat.MINI_GTFS:
        return ExportPreview(dependencies + ("agencias", "calendarios", "validación interna"))
    if request.format in {ExportFormat.COMPLETE_GTFS, ExportFormat.NEW_GTFS_VERSION}:
        return ExportPreview(
            (
                "todas las rutas",
                "viajes",
                "paradas",
                "shapes",
                "servicios",
                "agencias",
                "validación completa",
            )
        )
    if request.format in {ExportFormat.KML, ExportFormat.KMZ}:
        return ExportPreview(("rutas", "shapes", "paradas", "ExtendedData local"))
    return ExportPreview(dependencies)
