"""Controles encadenados ruta, servicio, direction_id y viaje."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.application.queries.map_layers import MapLayerPayload
from gtfs_explorer.application.queries.timetable import TimetableMatrix
from gtfs_explorer.domain.ports import PagedResult
from gtfs_explorer.domain.routes import (
    DirectionSummary,
    RouteSummary,
    ServiceSummary,
    TimelineStop,
    TripSummary,
)
from gtfs_explorer.domain.stops import StopInspection
from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.presentation.desktop.map.widget import MapWidget
from gtfs_explorer.presentation.desktop.stops.widget import StopInspectorWidget
from gtfs_explorer.presentation.desktop.timetable.widget import TimetableWidget
from gtfs_explorer.presentation.desktop.trips.widget import TripTimelineWidget


class RouteExplorerWidget(QWidget):
    """Mantiene una única selección relacional y reinicia descendientes de forma determinista."""

    def __init__(
        self,
        routes: Callable[[], PagedResult[RouteSummary]],
        services: Callable[[str], PagedResult[ServiceSummary]],
        directions: Callable[[str, str], PagedResult[DirectionSummary]],
        trips: Callable[[str, str, int | None], PagedResult[TripSummary]],
        timeline: Callable[[str], PagedResult[TimelineStop]],
        inspect_stop: Callable[[str], StopInspection],
        matrix: Callable[[str, str, int | None], TimetableMatrix],
        map_layers_for_trip: Callable[[str], MapLayerPayload] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._routes_query, self._services_query, self._directions_query = (
            routes,
            services,
            directions,
        )
        self._trips_query, self._matrix_query = trips, matrix
        layout = QVBoxLayout(self)
        filters = QGroupBox(t("routes.filters"))
        form = QFormLayout(filters)
        self._routes = QComboBox()
        self._routes.setObjectName("routeSelector")
        self._routes.setAccessibleName(t("routes.route_selector"))
        self._services = QComboBox()
        self._services.setObjectName("serviceSelector")
        self._services.setAccessibleName(t("routes.service_selector"))
        self._directions = QComboBox()
        self._directions.setObjectName("directionSelector")
        self._directions.setAccessibleName(t("routes.direction_selector"))
        self._trips = QComboBox()
        self._trips.setObjectName("tripSelector")
        self._trips.setAccessibleName(t("routes.trip_selector"))
        form.addRow(t("routes.route"), self._routes)
        form.addRow(t("routes.service"), self._services)
        form.addRow(t("routes.direction"), self._directions)
        form.addRow(t("routes.trip"), self._trips)
        matrix_button = QPushButton(t("routes.matrix"))
        matrix_button.setAccessibleDescription(t("routes.matrix_description"))
        matrix_button.clicked.connect(self._show_matrix)
        form.addRow(matrix_button)
        layout.addWidget(filters)
        details = QHBoxLayout()
        self._timeline = TripTimelineWidget(timeline, self._show_stop)
        self._stops = StopInspectorWidget(inspect_stop)
        details.addWidget(self._timeline)
        details.addWidget(self._stops)
        layout.addLayout(details, 1)
        self._map = MapWidget(map_layers_for_trip, self._show_stop) if map_layers_for_trip else None
        if self._map is not None:
            layout.addWidget(self._map, 1)
        self._timetable = TimetableWidget(self._selected_matrix)
        self._timetable.hide()
        if self._map is not None:
            self._map.clear()
        layout.addWidget(self._timetable)
        self._routes.currentIndexChanged.connect(self._route_changed)
        self._services.currentIndexChanged.connect(self._service_changed)
        self._directions.currentIndexChanged.connect(self._direction_changed)
        self._trips.currentIndexChanged.connect(self._trip_changed)
        self.setTabOrder(self._routes, self._services)
        self.setTabOrder(self._services, self._directions)
        self.setTabOrder(self._directions, self._trips)
        self.setTabOrder(self._trips, matrix_button)

    def refresh(self) -> None:
        self.clear()
        self._routes.blockSignals(True)
        for route in self._routes_query().items:
            name = route.short_name or route.long_name or "Sin nombre"
            self._routes.addItem(f"{name} ({route.route_id})", route)
        self._routes.blockSignals(False)
        if self._routes.count():
            self._routes.setCurrentIndex(0)
            self._route_changed()

    def clear(self) -> None:
        for selector in (self._routes, self._services, self._directions, self._trips):
            selector.blockSignals(True)
            selector.clear()
            selector.blockSignals(False)
        self._timeline.clear()
        self._stops.clear()
        self._clear_map()
        self._timetable.clear()
        self._timetable.hide()

    def set_map_package(self, root: Path) -> str:
        """Selecciona un mapa local; el error de validación se propaga a la UI."""
        if self._map is None:
            raise RuntimeError("El mapa no está disponible.")
        return self._map.set_map_package(root).attribution

    def _route_changed(self) -> None:
        self._reset(self._services, self._directions, self._trips)
        self._timeline.clear()
        self._stops.clear()
        self._clear_map()
        self._timetable.hide()
        route = self._routes.currentData()
        if not isinstance(route, RouteSummary):
            return
        for service in self._services_query(route.route_id).items:
            self._services.addItem(f"{service.service_id} ({service.trip_count} viajes)", service)
        if self._services.count():
            self._services.setCurrentIndex(0)
            self._service_changed()

    def _service_changed(self) -> None:
        self._reset(self._directions, self._trips)
        self._timeline.clear()
        self._stops.clear()
        self._clear_map()
        self._timetable.hide()
        route, service = self._routes.currentData(), self._services.currentData()
        if not isinstance(route, RouteSummary) or not isinstance(service, ServiceSummary):
            return
        for direction in self._directions_query(route.route_id, service.service_id).items:
            label = (
                "sin declarar" if direction.direction_id is None else str(direction.direction_id)
            )
            self._directions.addItem(
                f"direction_id: {label} ({direction.trip_count} viajes)", direction
            )
        if self._directions.count():
            self._directions.setCurrentIndex(0)
            self._direction_changed()

    def _direction_changed(self) -> None:
        self._reset(self._trips)
        self._timeline.clear()
        self._stops.clear()
        self._clear_map()
        self._timetable.hide()
        route, service, direction = self._selection()
        if route is None or service is None or direction is None:
            return
        for trip in self._trips_query(
            route.route_id, service.service_id, direction.direction_id
        ).items:
            name = trip.headsign or trip.short_name or "Sin nombre"
            self._trips.addItem(f"{name} ({trip.trip_id})", trip)
        if self._trips.count():
            self._trips.setCurrentIndex(0)
            self._trip_changed()

    def _trip_changed(self) -> None:
        trip = self._trips.currentData()
        self._timeline.clear()
        self._stops.clear()
        self._clear_map()
        if isinstance(trip, TripSummary):
            self._timeline.show_trip(trip)
            if self._map is not None:
                self._map.show_trip(trip.trip_id)

    def _show_stop(self, stop_id: str) -> None:
        self._stops.show_stop(stop_id)
        self._timeline.select_stop(stop_id)
        if self._map is not None:
            self._map.select_stop(stop_id)

    def _clear_map(self) -> None:
        if self._map is not None:
            self._map.clear()

    def _show_matrix(self) -> None:
        self._timetable.show()
        self._timetable.refresh()

    def _selected_matrix(self) -> TimetableMatrix | None:
        route, service, direction = self._selection()
        return (
            None
            if route is None or service is None or direction is None
            else self._matrix_query(route.route_id, service.service_id, direction.direction_id)
        )

    def _selection(
        self,
    ) -> tuple[RouteSummary | None, ServiceSummary | None, DirectionSummary | None]:
        route, service, direction = (
            self._routes.currentData(),
            self._services.currentData(),
            self._directions.currentData(),
        )
        return (
            route if isinstance(route, RouteSummary) else None,
            service if isinstance(service, ServiceSummary) else None,
            direction if isinstance(direction, DirectionSummary) else None,
        )

    @staticmethod
    def _reset(*selectors: QComboBox) -> None:
        for selector in selectors:
            selector.blockSignals(True)
            selector.clear()
            selector.blockSignals(False)
