"""Vista de matriz por patrón de paradas."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from gtfs_explorer.application.queries.timetable import TimetableCell, TimetableMatrix
from gtfs_explorer.presentation.desktop.i18n import t


class TimetableWidget(QWidget):
    """Expone una vista previa acotada, agrupada por patrón GTFS."""

    def __init__(
        self,
        matrix_for_selection: Callable[[], TimetableMatrix | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._matrix_for_selection = matrix_for_selection
        layout = QVBoxLayout(self)
        self._headline = QLabel()
        self._headline.setObjectName("timetableHeadline")
        layout.addWidget(self._headline)
        self._table = QTableWidget()
        self._table.setObjectName("timetableMatrix")
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._set_translated_labels()
        layout.addWidget(self._table)

    def clear(self) -> None:
        self._headline.setText(t("timetable.select_prompt"))
        self._table.clear()
        self._table.setRowCount(0)
        self._table.setColumnCount(0)

    def retranslate_ui(self) -> None:
        """Actualiza textos sin reconstruir el feed ni cambiar la selección."""
        self._set_translated_labels()
        if self.isVisible():
            self.refresh()
        else:
            self.clear()

    def refresh(self) -> None:
        matrix = self._matrix_for_selection()
        if matrix is None:
            self.clear()
            return
        if not matrix.patterns:
            self._headline.setText(t("timetable.no_trips"))
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            return
        pattern = matrix.patterns[0]
        self._headline.setText(
            t(
                "timetable.pattern_summary",
                current=1,
                total=len(matrix.patterns),
                trips=matrix.total_trips,
            )
            + (t("timetable.pattern_truncated") if matrix.truncated else ".")
        )
        self._table.setColumnCount(len(pattern.columns) + 1)
        self._table.setRowCount(len(pattern.rows))
        self._table.setHorizontalHeaderLabels(
            (t("timetable.stop_header"), *(column.trip_id for column in pattern.columns))
        )
        for row, stop in enumerate(pattern.rows):
            stop_name = stop.stop_name or t("stop.name_unknown")
            stop_id = stop.stop_id or t("stop.id_unknown")
            self._table.setItem(
                row,
                0,
                QTableWidgetItem(t("timetable.stop_item", name=stop_name, stop_id=stop_id)),
            )
            for column, trip in enumerate(pattern.columns, start=1):
                cell = trip.cells[row]
                self._table.setItem(row, column, QTableWidgetItem(_format_cell(cell)))
        self._table.resizeColumnsToContents()

    def _set_translated_labels(self) -> None:
        self._headline.setText(t("timetable.select_prompt"))
        self._table.setAccessibleName(t("timetable.accessible"))


def _format_cell(cell: TimetableCell) -> str:
    """Distingue los dos campos GTFS aunque solo uno esté informado."""
    values = []
    if cell.arrival_time:
        values.append(t("timetable.arrival_cell", value=cell.arrival_time))
    if cell.departure_time:
        values.append(t("timetable.departure_cell", value=cell.departure_time))
    return " · ".join(values) or t("stop.not_available")
