"""Asistente de exportación: contrato de UI y ayudas seguras por formato."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
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


Previewer = Callable[[ExportRequest], ExportPreview]
Executor = Callable[[ExportRequest, Callable[[], bool]], ExportResult]


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
    ) -> None:
        super().__init__(parent)
        self._previewer = previewer or _default_preview
        self._executor = executor
        self._default_directory_resolver = default_directory_resolver
        self._prepare_default_directory = prepare_default_directory
        self._on_destination_directory_used = on_destination_directory_used
        self._cancelled = False
        self._suggested_destination_text = ""
        self._route_options: tuple[ExportRouteOption, ...] = ()
        self._service_options: tuple[ExportServiceOption, ...] = ()
        self._build()
        self._refresh()

    def set_executor(self, executor: Executor | None) -> None:
        self._executor = executor
        self._refresh()

    def clear(self) -> None:
        """Elimina toda selección y destino dependientes del proyecto actual."""
        self._cancelled = False
        self._suggested_destination_text = ""
        self._format.blockSignals(True)
        self._format.setCurrentIndex(0)
        self._format.blockSignals(False)
        for editor in (self._routes, self._trips, self._services):
            editor.clear()
        self.set_inventory((), ())
        self._destination.clear()
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
        format_label = QLabel(t("export.format_label"))
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
        self._route_search.setPlaceholderText("Buscar rutas")
        self._route_inventory = QListWidget()
        self._route_inventory.setObjectName("exportRouteInventory")
        self._route_inventory.setAccessibleName(t("export.routes"))
        self._route_inventory.setMaximumHeight(130)
        route_controls = QHBoxLayout()
        all_routes = QPushButton("Seleccionar todas")
        clear_routes = QPushButton("Limpiar")
        route_controls.addWidget(all_routes)
        route_controls.addWidget(clear_routes)
        route_box = QVBoxLayout()
        route_box.addWidget(self._route_search)
        route_box.addWidget(self._route_inventory)
        route_box.addLayout(route_controls)
        form.addRow(QLabel(t("export.routes_label")), route_box)
        self._service_inventory = QListWidget()
        self._service_inventory.setObjectName("exportServiceInventory")
        self._service_inventory.setAccessibleName(t("export.services"))
        self._service_inventory.setMaximumHeight(110)
        service_controls = QHBoxLayout()
        all_services = QPushButton("Seleccionar todos")
        clear_services = QPushButton("Limpiar")
        service_controls.addWidget(all_services)
        service_controls.addWidget(clear_services)
        service_box = QVBoxLayout()
        service_box.addWidget(self._service_inventory)
        service_box.addLayout(service_controls)
        form.addRow(QLabel(t("export.services_label")), service_box)
        # Los viajes siguen disponibles como filtro avanzado, no como requisito normal.
        for label_text, editor in ((t("export.trips_label") + " (avanzado)", self._trips),):
            label = QLabel(label_text)
            label.setBuddy(editor)
            form.addRow(label, editor)
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
        browse.setAccessibleName(t("export.browse"))
        browse.setAccessibleDescription(t("export.browse_description"))
        browse.setToolTip(t("export.browse"))
        browse.clicked.connect(self._choose_destination)
        destination_row.addWidget(self._destination)
        destination_row.addWidget(browse)
        destination_label = QLabel(t("export.destination_label"))
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
        needs_routes = True
        self._routes.setEnabled(needs_routes)
        self._trips.setEnabled(needs_routes)
        self._services.setEnabled(needs_routes)
        self._bbox.setEnabled(format_ is ExportFormat.GEOJSON)
        self._spreadsheet_safe.setEnabled(format_ is ExportFormat.CSV)
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
        self._sync_proposed_destination(proposed_name if route_ids else "")
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
        if not request.destination.name:
            self._preview.setText(t("export.preview_missing_destination"))
            self._export.setEnabled(False)
            return
        preview = self._previewer(request)
        selection_summary = (
            f"{len(request.route_ids)} rutas · {len(request.service_ids)} servicios · "
            f"{len(request.trip_ids)} viajes"
        )
        lines = [
            selection_summary,
            t(
                "export.preview_dependencies",
                dependencies=", ".join(preview.dependencies) or t("export.preview_no_dependencies"),
            ),
        ]
        if request.is_pack:
            lines.insert(1, "Export Pack")
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
        if self._executor is None:
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
        self._export.setEnabled(False)
        self._cancel.setEnabled(True)
        try:
            result = self._executor(request, lambda: self._cancelled)
        except Exception:
            QMessageBox.critical(
                self,
                t("dialog.export_error_title"),
                t("dialog.export_error_message"),
                QMessageBox.StandardButton.Ok,
            )
            return
        finally:
            self._cancel.setEnabled(False)
            self._refresh()
        warnings = "\n".join(
            t("export.preview_warning", warning=item) for item in result.warnings
        ) or t("export.no_warnings")
        self._show_export_completed(request.destination, result, warnings)

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

    def _request_cancel(self) -> None:
        self._cancelled = True
        self._cancel.setEnabled(False)

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
    return ExportPreview(dependencies)
