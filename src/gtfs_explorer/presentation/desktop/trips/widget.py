"""Timeline paginado de un viaje GTFS."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from gtfs_explorer.domain.ports import PagedResult
from gtfs_explorer.domain.routes import TimelineStop, TripSummary
from gtfs_explorer.presentation.desktop.i18n import t


class TripTimelineWidget(QWidget):
    """Presenta los tiempos GTFS literalmente, incluidos los superiores a 24 horas."""

    def __init__(
        self,
        timeline_for_trip: Callable[[str], PagedResult[TimelineStop]],
        on_stop_selected: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._timeline_for_trip = timeline_for_trip
        self._on_stop_selected = on_stop_selected
        self._trip: TripSummary | None = None
        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, 5)
        self._table.setObjectName("tripTimeline")
        self._set_translated_labels()
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._select_stop)
        layout.addWidget(self._table)

    def clear(self) -> None:
        self._trip = None
        self._table.setRowCount(0)

    def show_trip(self, trip: TripSummary) -> None:
        self._trip = trip
        page = self._timeline_for_trip(trip.trip_id)
        self._table.setRowCount(len(page.items))
        for row, stop in enumerate(page.items):
            values = (
                "" if stop.stop_sequence is None else str(stop.stop_sequence),
                stop.stop_name or t("stop.name_unknown"),
                stop.stop_id or t("stop.id_unknown"),
                stop.arrival_time or t("stop.not_available"),
                stop.departure_time or t("stop.not_available"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 2:
                    item.setData(256, stop.stop_id)
                self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()

    def retranslate_ui(self) -> None:
        """Actualiza cabeceras y los valores de reserva del timeline."""
        selected_stop_id = None
        selected = self._table.selectedItems()
        if selected:
            selected_stop_id = selected[0].data(256)
        self._set_translated_labels()
        if self._trip is not None:
            self.show_trip(self._trip)
            if isinstance(selected_stop_id, str):
                self.select_stop(selected_stop_id)

    def _set_translated_labels(self) -> None:
        self._table.setHorizontalHeaderLabels(
            (
                t("stop.sequence"),
                t("stop.name"),
                t("stop.stop_id"),
                t("trip.arrival_header"),
                t("trip.departure_header"),
            )
        )
        self._table.setAccessibleName(t("trip.timeline_accessible"))

    def select_stop(self, stop_id: str) -> None:
        """Refleja un click de mapa sin disparar una segunda consulta de parada."""
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 2)
            if item is not None and item.data(256) == stop_id:
                self._table.blockSignals(True)
                self._table.selectRow(row)
                self._table.blockSignals(False)
                return

    def _select_stop(self) -> None:
        selected = self._table.selectedItems()
        if not selected:
            return
        stop_item = self._table.item(selected[0].row(), 2)
        if stop_item is None:
            return
        stop_id = stop_item.data(256)
        if isinstance(stop_id, str):
            self._on_stop_selected(stop_id)
