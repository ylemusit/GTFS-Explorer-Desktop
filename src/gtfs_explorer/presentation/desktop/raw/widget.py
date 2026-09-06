"""Vista raw con filtros estructurados y acciones explícitas sobre datos cargados."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.domain.raw import RawFilter, RawQuery
from gtfs_explorer.infrastructure.exporting.csv_exporter import (
    CsvExporter,
    CsvExportMode,
    CsvExportOptions,
)
from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.presentation.models.paged_table import PagedTableModel, RawQueryExecutor

RAW_SIZING_SAMPLE_ROWS = 24
RAW_SIZING_MIN_WIDTH = 72
RAW_SIZING_MAX_WIDTH = 320
RAW_SIZING_HORIZONTAL_PADDING = 24


class RawInspectorWidget(QWidget):
    """Permite explorar staging sin formular SQL ni cargar más de una página bajo demanda."""

    def __init__(
        self,
        execute: RawQueryExecutor,
        parent: QWidget | None = None,
        *,
        export_directory_resolver: Callable[[], Path] | None = None,
        prepare_export_directory: Callable[[], Path] | None = None,
        on_export_directory_used: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = PagedTableModel(execute, self)
        self._model.load_failed.connect(self._show_error)
        self._fields: dict[str, tuple[str, ...]] = {}
        self._export_directory_resolver = export_directory_resolver
        self._prepare_export_directory = prepare_export_directory
        self._on_export_directory_used = on_export_directory_used
        self._build_layout()

    def configure(self, files: dict[str, tuple[str, ...]]) -> None:
        self._fields = files
        self._files.blockSignals(True)
        self._files.clear()
        self._files.addItems(sorted(files))
        self._files.blockSignals(False)
        if files:
            self._change_file()
        else:
            self._field.clear()
            self._model.clear()

    def clear(self) -> None:
        self._fields = {}
        self._files.blockSignals(True)
        self._files.clear()
        self._files.blockSignals(False)
        self._field.clear()
        self._filter.clear()
        self._table.clearSelection()
        self._model.clear()

    def inspect_location(
        self, filename: str, field_name: str | None, entity_id: str | None
    ) -> None:
        """Abre un origen de validación sin exponer una consulta SQL a la interfaz."""
        index = self._files.findText(filename)
        if index < 0:
            return
        self._files.setCurrentIndex(index)
        if field_name and self._field.findText(field_name) >= 0:
            self._field.setCurrentText(field_name)
        if entity_id:
            self._filter.setText(entity_id)
            self._apply_filter()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        self._description = QLabel(t("raw.description"))
        layout.addWidget(self._description)
        controls = QHBoxLayout()
        self._files = QComboBox()
        self._files.setAccessibleName(t("raw.file"))
        self._files.currentTextChanged.connect(self._change_file)
        self._field = QComboBox()
        self._field.setAccessibleName(t("raw.field"))
        self._filter = QLineEdit()
        self._filter.setAccessibleName(t("raw.filter"))
        self._filter.setPlaceholderText(t("raw.filter_placeholder"))
        apply_filter = QPushButton(t("raw.apply"))
        self._apply_button = apply_filter
        apply_filter.setAccessibleName(t("raw.apply"))
        apply_filter.setToolTip(t("raw.apply"))
        apply_filter.clicked.connect(self._apply_filter)
        copy = QPushButton(t("raw.copy"))
        self._copy_button = copy
        copy.setAccessibleName(t("raw.copy"))
        copy.setToolTip(t("raw.copy"))
        copy.clicked.connect(self._copy_selection)
        export = QPushButton(t("raw.export"))
        self._export_button = export
        export.setAccessibleName(t("raw.export"))
        export.setToolTip(t("raw.export"))
        export.clicked.connect(self._export_loaded)
        for widget in (self._files, self._field, self._filter, apply_filter, copy, export):
            controls.addWidget(widget)
        layout.addLayout(controls)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectItems)
        self._table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._model.modelReset.connect(self._apply_smart_column_sizing)
        self._table.setAccessibleName(t("raw.table"))
        layout.addWidget(self._table)
        self.setTabOrder(self._files, self._field)
        self.setTabOrder(self._field, self._filter)
        self.setTabOrder(self._filter, apply_filter)
        self.setTabOrder(apply_filter, copy)
        self.setTabOrder(copy, export)
        self.setTabOrder(export, self._table)

    def retranslate_ui(self) -> None:
        """Actualiza los controles raw sin cambiar la consulta ni sus filas."""
        self._description.setText(t("raw.description"))
        self._files.setAccessibleName(t("raw.file"))
        self._field.setAccessibleName(t("raw.field"))
        self._filter.setAccessibleName(t("raw.filter"))
        self._filter.setPlaceholderText(t("raw.filter_placeholder"))
        for button, key in (
            (self._apply_button, "raw.apply"),
            (self._copy_button, "raw.copy"),
            (self._export_button, "raw.export"),
        ):
            button.setText(t(key))
            button.setAccessibleName(t(key))
            button.setToolTip(t(key))
        self._table.setAccessibleName(t("raw.table"))

    def _change_file(self) -> None:
        filename = self._files.currentText()
        fields = self._fields.get(filename, ())
        self._field.clear()
        self._field.addItems(fields)
        if fields:
            self._model.set_query(RawQuery(filename, fields[: min(10, len(fields))]))

    def _apply_filter(self) -> None:
        filename = self._files.currentText()
        columns = self._fields.get(filename, ())[:10]
        if not filename or not columns:
            return
        text = self._filter.text()
        filters = () if not text else (RawFilter(self._field.currentText(), "contains", text),)
        self._model.set_query(RawQuery(filename, columns, filters=filters))

    def _copy_selection(self) -> None:
        rows = self._model.selected_rows(self._table.selectionModel().selectedIndexes())
        if not rows:
            return
        QGuiApplication.clipboard().setText("\n".join("\t".join(row) for row in rows))

    def _export_loaded(self) -> None:
        if not self._model.rowCount():
            return
        directory = (
            self._prepare_export_directory()
            if self._prepare_export_directory is not None
            else self._export_directory()
        )
        initial = (
            str(directory / "vista-raw-faithful.csv")
            if directory is not None
            else "vista-raw-faithful.csv"
        )
        destination, _ = QFileDialog.getSaveFileName(
            self,
            t("dialog.raw_export_title"),
            initial,
            t("dialog.raw_csv_filter"),
        )
        if not destination:
            return
        path = Path(destination)
        if not path.name.endswith("-faithful.csv"):
            path = path.with_name(path.stem + "-faithful.csv")
        try:
            CsvExporter().write(
                path,
                # ``Fila fuente`` es metadata de la vista, no una columna GTFS.
                headers=self._model.headers()[1:],
                rows=tuple(row[1:] for row in self._model.loaded_rows()),
                options=CsvExportOptions(mode=CsvExportMode.FAITHFUL),
                overwrite=path.exists(),
            )
            if self._on_export_directory_used is not None:
                self._on_export_directory_used(path.parent)
        except Exception:
            self._show_error()

    def _export_directory(self) -> Path | None:
        if self._export_directory_resolver is None:
            return None
        return self._export_directory_resolver()

    def _show_error(self, _message: str = "") -> None:
        QMessageBox.warning(
            self,
            t("dialog.raw_export_error_title"),
            t("dialog.raw_export_error_message"),
            QMessageBox.StandardButton.Ok,
        )

    def _apply_smart_column_sizing(self) -> None:
        """Ajusta solo la página cargada, sin consultar el total del staging."""
        headers = self._model.headers()
        if not headers:
            return
        rows = self._model.loaded_rows()[:RAW_SIZING_SAMPLE_ROWS]
        metrics = self._table.fontMetrics()
        header = self._table.horizontalHeader()
        for column, name in enumerate(headers):
            candidates = [name]
            candidates.extend(row[column] for row in rows if column < len(row))
            measured = max(metrics.horizontalAdvance(value[:80]) for value in candidates if value)
            width = max(
                RAW_SIZING_MIN_WIDTH,
                min(RAW_SIZING_MAX_WIDTH, measured + RAW_SIZING_HORIZONTAL_PADDING),
            )
            header.resizeSection(column, width)
