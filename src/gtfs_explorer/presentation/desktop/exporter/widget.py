"""Asistente de exportación: contrato de UI y ayudas seguras por formato."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.domain.exporting import ExportManifest
from gtfs_explorer.presentation.desktop.i18n import t


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


@dataclass(frozen=True)
class ExportPreview:
    """Dependencias que se incluirán; nunca promete que una salida sea oficial."""

    dependencies: tuple[str, ...]
    warnings: tuple[str, ...] = ()


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
    ) -> None:
        super().__init__(parent)
        self._previewer = previewer or _default_preview
        self._executor = executor
        self._cancelled = False
        self._build()
        self._refresh()

    def set_executor(self, executor: Executor | None) -> None:
        self._executor = executor
        self._refresh()

    def request(self) -> ExportRequest:
        format_ = ExportFormat(self._format.currentData())
        destination = _effective_destination(
            format_, Path(self._destination.text()), self._spreadsheet_safe.isChecked()
        )
        return ExportRequest(
            format_,
            destination,
            route_ids=_identifiers(self._routes.toPlainText()),
            trip_ids=_identifiers(self._trips.toPlainText()),
            service_ids=_identifiers(self._services.toPlainText()),
            include_bbox=self._bbox.isChecked(),
            spreadsheet_safe=self._spreadsheet_safe.isChecked(),
            overwrite=destination.exists(),
        )

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        description = QLabel(
            "Seleccione rutas y, si procede, viajes o servicios. El cierre de dependencias "
            "se previsualiza antes de escribir en el equipo."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self._format = QComboBox()
        self._format.setObjectName("exportFormat")
        self._format.setAccessibleName(t("export.format"))
        self._format.addItem("JSON bundle (derivada)", ExportFormat.JSON.value)
        self._format.addItem("GeoJSON (compatible)", ExportFormat.GEOJSON.value)
        self._format.addItem("CSV (compatible)", ExportFormat.CSV.value)
        self._format.addItem(
            "Mini-GTFS (oficial si supera validación)", ExportFormat.MINI_GTFS.value
        )
        form.addRow("Formato:", self._format)
        self._routes = _identifiers_editor("exportRoutes")
        self._trips = _identifiers_editor("exportTrips")
        self._services = _identifiers_editor("exportServices")
        self._routes.setAccessibleName(t("export.routes"))
        self._trips.setAccessibleName(t("export.trips"))
        self._services.setAccessibleName(t("export.services"))
        form.addRow("Rutas (una por línea):", self._routes)
        form.addRow("Viajes opcionales:", self._trips)
        form.addRow("Servicios opcionales:", self._services)
        destination_row = QHBoxLayout()
        self._destination = QLineEdit()
        self._destination.setObjectName("exportDestination")
        self._destination.setAccessibleName(t("export.destination"))
        browse = QPushButton(t("export.browse"))
        browse.clicked.connect(self._choose_destination)
        destination_row.addWidget(self._destination)
        destination_row.addWidget(browse)
        form.addRow("Destino:", destination_row)
        self._bbox = QCheckBox("Incluir bbox GeoJSON")
        self._bbox.setObjectName("exportBbox")
        self._spreadsheet_safe = QCheckBox("Neutralizar fórmulas para hoja de cálculo")
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
        self._cancel = QPushButton(t("export.cancel"))
        self._cancel.setObjectName("exportCancel")
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
        self._bbox.toggled.connect(self._refresh)
        self._spreadsheet_safe.toggled.connect(self._refresh)

    def _refresh(self) -> None:
        format_ = ExportFormat(self._format.currentData())
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
        self._format_help.setText(_format_help(format_))
        request = self.request()
        if needs_routes and not request.route_ids:
            self._preview.setText("Seleccione al menos una ruta: el cierre no puede calcularse.")
            self._export.setEnabled(False)
            return
        if not request.destination.name:
            self._preview.setText("Seleccione un archivo de destino local.")
            self._export.setEnabled(False)
            return
        preview = self._previewer(request)
        lines = ["Dependencias: " + (", ".join(preview.dependencies) or "ninguna.")]
        lines.extend(f"Aviso: {warning}" for warning in preview.warnings)
        if request.destination.exists():
            lines.append("El destino ya existe: se pedirá confirmación antes de sobrescribirlo.")
        self._preview.setText("\n".join(lines))
        self._export.setEnabled(self._executor is not None)

    def _choose_destination(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar GTFS")
        if path:
            self._destination.setText(path)

    def _execute(self) -> None:
        if self._executor is None:
            return
        request = self.request()
        if (
            request.destination.exists()
            and QMessageBox.question(
                self,
                "Sobrescribir exportación",
                f"Ya existe '{request.destination.name}'. ¿Sobrescribir?",
            )
            is not QMessageBox.StandardButton.Yes
        ):
            return
        self._cancelled = False
        self._export.setEnabled(False)
        self._cancel.setEnabled(True)
        try:
            result = self._executor(request, lambda: self._cancelled)
        except Exception as error:
            QMessageBox.critical(self, "No se pudo exportar", str(error) or type(error).__name__)
            return
        finally:
            self._cancel.setEnabled(False)
            self._refresh()
        warnings = "\n".join(f"Aviso: {item}" for item in result.warnings) or "Sin avisos."
        QMessageBox.information(
            self,
            "Exportación completada",
            f"Salida {result.classification}.\nSHA-256: {result.manifest.sha256}\n{warnings}",
            QMessageBox.StandardButton.Ok,
        )

    def _request_cancel(self) -> None:
        self._cancelled = True
        self._cancel.setEnabled(False)


def _identifiers(value: str) -> frozenset[str]:
    return frozenset(line.strip() for line in value.splitlines() if line.strip())


def _identifiers_editor(name: str) -> QPlainTextEdit:
    editor = QPlainTextEdit()
    editor.setObjectName(name)
    editor.setMaximumHeight(58)
    return editor


def _format_help(format_: ExportFormat) -> str:
    return {
        ExportFormat.JSON: "Salida derivada: bundle propio de GTFS Explorer, no GTFS oficial.",
        ExportFormat.GEOJSON: (
            "Salida compatible RFC 7946; contiene geometría, no un feed GTFS oficial."
        ),
        ExportFormat.CSV: "Salida compatible CSV; no es un feed GTFS oficial.",
        ExportFormat.MINI_GTFS: (
            "Salida oficial solo si supera la reimportación y validación Mini-GTFS."
        ),
    }[format_]


def _effective_destination(
    format_: ExportFormat, destination: Path, spreadsheet_safe: bool
) -> Path:
    """Devuelve el artefacto real antes de comprobar overwrite.

    CSV obliga a hacer visible su modo en el nombre. La confirmación de
    sobrescritura debe referirse a ese archivo final, no al texto intermedio
    escrito por la persona usuaria.
    """
    if format_ is not ExportFormat.CSV:
        return destination
    mode = "spreadsheet-safe" if spreadsheet_safe else "faithful"
    return destination.with_name(destination.stem + f"-{mode}.csv")


def _default_preview(request: ExportRequest) -> ExportPreview:
    if request.format is ExportFormat.CSV:
        return ExportPreview(("cabecera y filas de la vista seleccionada",))
    dependencies = ("rutas", "viajes", "paradas", "servicios")
    if request.format is ExportFormat.MINI_GTFS:
        return ExportPreview(dependencies + ("agencias", "calendarios", "validación interna"))
    return ExportPreview(dependencies)
