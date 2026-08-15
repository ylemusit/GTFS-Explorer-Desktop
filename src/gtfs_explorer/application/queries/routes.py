"""Casos de uso para explorar la cadena ruta, viaje y parada."""

from __future__ import annotations

from gtfs_explorer.domain.ports import PagedResult, PageRequest, RouteExplorerRepository
from gtfs_explorer.domain.routes import (
    DirectionSummary,
    RouteSummary,
    ServiceSummary,
    TimelineStop,
    TripSummary,
)


class RouteExplorerQueries:
    """Expone filtros encadenados sin atribuir significado a ``direction_id``."""

    def __init__(self, repository: RouteExplorerRepository) -> None:
        self._repository = repository

    def routes(self, page: PageRequest) -> PagedResult[RouteSummary]:
        return self._repository.routes(page)

    def services_for_route(self, route_id: str, page: PageRequest) -> PagedResult[ServiceSummary]:
        return self._repository.services_for_route(route_id, page)

    def directions_for_route_service(
        self, route_id: str, service_id: str, page: PageRequest
    ) -> PagedResult[DirectionSummary]:
        return self._repository.directions_for_route_service(route_id, service_id, page)

    def trips_for_route_service_direction(
        self, route_id: str, service_id: str, direction_id: int | None, page: PageRequest
    ) -> PagedResult[TripSummary]:
        return self._repository.trips_for_route_service_direction(
            route_id, service_id, direction_id, page
        )

    def trip_timeline(self, trip_id: str, page: PageRequest) -> PagedResult[TimelineStop]:
        return self._repository.trip_timeline(trip_id, page)
