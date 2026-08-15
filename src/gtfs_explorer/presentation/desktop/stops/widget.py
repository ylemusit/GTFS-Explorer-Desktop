"""Inspector de una parada y sus eventos programados."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from gtfs_explorer.domain.stops import StopInspection


class StopInspectorWidget(QWidget):
    """Muestra contexto de parada; los eventos no se presentan como tiempo real."""

    def __init__(
        self, inspect_stop: Callable[[str], StopInspection], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._inspect_stop = inspect_stop
        layout = QVBoxLayout(self)
        self._headline = QLabel("Seleccione una parada en el timeline.")
        self._headline.setObjectName("stopInspectorHeadline")
        layout.addWidget(self._headline)
        self._events = QTableWidget(0, 5)
        self._events.setObjectName("stopScheduledEvents")
        self._events.setHorizontalHeaderLabels(("Ruta", "ID ruta", "Viaje", "Llegada", "Salida"))
        self._events.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._events.setAccessibleName("Eventos programados de la parada")
        layout.addWidget(self._events)

    def clear(self) -> None:
        self._headline.setText("Seleccione una parada en el timeline.")
        self._events.setRowCount(0)

    def show_stop(self, stop_id: str) -> None:
        inspection = self._inspect_stop(stop_id)
        if inspection.stop is None:
            self._headline.setText(f"Parada no encontrada: {stop_id}")
            self._events.setRowCount(0)
            return
        name = inspection.stop.name or "Sin nombre"
        self._headline.setText(f"Parada: {name} ({inspection.stop.stop_id}) — horarios programados")
        events = inspection.scheduled_events.items
        self._events.setRowCount(len(events))
        for row, event in enumerate(events):
            route_name = event.route.short_name or event.route.long_name or "Sin nombre"
            for column, value in enumerate(
                (
                    route_name,
                    event.route.route_id,
                    event.trip_id,
                    event.arrival_time or "—",
                    event.departure_time or "—",
                )
            ):
                self._events.setItem(row, column, QTableWidgetItem(value))
        self._events.resizeColumnsToContents()
