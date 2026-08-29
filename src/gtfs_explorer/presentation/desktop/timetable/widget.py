"""Vista de matriz por patrón de paradas."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from gtfs_explorer.application.queries.timetable import TimetableCell, TimetableMatrix


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
        self._headline = QLabel("Seleccione ruta, servicio y direction_id para ver la matriz.")
        self._headline.setObjectName("timetableHeadline")
        layout.addWidget(self._headline)
        self._table = QTableWidget()
        self._table.setObjectName("timetableMatrix")
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAccessibleName("Matriz de horarios por patrón")
        layout.addWidget(self._table)

    def clear(self) -> None:
        self._headline.setText("Seleccione ruta, servicio y direction_id para ver la matriz.")
        self._table.clear()
        self._table.setRowCount(0)
        self._table.setColumnCount(0)

    def refresh(self) -> None:
        matrix = self._matrix_for_selection()
        if matrix is None:
            self.clear()
            return
        if not matrix.patterns:
            self._headline.setText("No hay viajes para esta selección.")
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            return
        pattern = matrix.patterns[0]
        self._headline.setText(
            f"Patrón 1 de {len(matrix.patterns)}; {matrix.total_trips} viaje(s) en total"
            + ("; vista previa limitada." if matrix.truncated else ".")
        )
        self._table.setColumnCount(len(pattern.columns) + 1)
        self._table.setRowCount(len(pattern.rows))
        self._table.setHorizontalHeaderLabels(
            ("Parada", *(column.trip_id for column in pattern.columns))
        )
        for row, stop in enumerate(pattern.rows):
            self._table.setItem(
                row,
                0,
                QTableWidgetItem(f"{stop.stop_name or 'Sin nombre'} ({stop.stop_id or 'Sin ID'})"),
            )
            for column, trip in enumerate(pattern.columns, start=1):
                cell = trip.cells[row]
                self._table.setItem(row, column, QTableWidgetItem(_format_cell(cell)))
        self._table.resizeColumnsToContents()


def _format_cell(cell: TimetableCell) -> str:
    """Distingue los dos campos GTFS aunque solo uno esté informado."""
    values = []
    if cell.arrival_time:
        values.append(f"arrival_time: {cell.arrival_time}")
    if cell.departure_time:
        values.append(f"departure_time: {cell.departure_time}")
    return " · ".join(values) or "—"
