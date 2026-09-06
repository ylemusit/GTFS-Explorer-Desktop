"""Datos del inspector de paradas de un feed GTFS Schedule."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from .routes import RouteSummary, ServiceSummary

if TYPE_CHECKING:
    from .ports import PagedResult


@dataclass(frozen=True)
class StopSummary:
    stop_id: str
    name: str | None
    parent_station: str | None


@dataclass(frozen=True)
class StopCard:
    """Modelo único de presentación para una parada en mapa y explorador."""

    stop_id: str
    name: str | None = None
    route_id: str | None = None
    route_short_name: str | None = None
    route_long_name: str | None = None
    route_color: str | None = None
    endpoint: str | None = None
    arrival: str | None = None
    departure: str | None = None
    sequence: int | None = None
    previous_stop: str | None = None
    next_stop: str | None = None
    previous_stop_name: str | None = None
    next_stop_name: str | None = None
    dwell_seconds: int | None = None
    agency: str | None = None
    agency_id: str | None = None
    trip_id: str | None = None
    service_id: str | None = None
    headsign: str | None = None
    other_routes: tuple[dict[str, Any], ...] = ()

    @property
    def route_label(self) -> str:
        return (
            " · ".join(value for value in (self.route_short_name, self.route_long_name) if value)
            or self.route_id
            or ""
        )

    def to_payload(self) -> dict[str, object]:
        """Serializa aliases históricos y los campos de la ficha humana."""
        return {
            "stop_id": self.stop_id,
            "name": self.name or "",
            "selected_route_id": self.route_id or "",
            "route_id": self.route_id or "",
            "route_short_name": self.route_short_name or "",
            "route_long_name": self.route_long_name or "",
            "route_color": self.route_color or "",
            "route": self.route_label,
            "headsign": self.headsign or "",
            "agency_id": self.agency_id or "",
            "agency": self.agency or self.agency_id or "",
            "service_id": self.service_id or "",
            "trip_id": self.trip_id or "",
            "arrival": self.arrival or "",
            "departure": self.departure or "",
            "arrival_time": self.arrival or "",
            "departure_time": self.departure or "",
            "sequence": self.sequence,
            "endpoint": self.endpoint or "",
            "previous_stop": self.previous_stop or "",
            "next_stop": self.next_stop or "",
            "previous_stop_name": self.previous_stop_name or self.previous_stop or "",
            "next_stop_name": self.next_stop_name or self.next_stop or "",
            "dwell_seconds": self.dwell_seconds,
            "other_routes": [dict(route) for route in self.other_routes],
            "trips_context": [
                {
                    "trip_id": self.trip_id or "",
                    "route_id": self.route_id or "",
                    "service_id": self.service_id or "",
                }
            ]
            if self.trip_id or self.route_id
            else [],
        }


@dataclass(frozen=True)
class ScheduledStopEvent:
    """Evento procedente del horario GTFS importado, no una predicción."""

    trip_id: str
    route: RouteSummary
    service_id: str
    stop_id: str
    stop_name: str | None
    stop_sequence: int | None
    arrival_time: str | None
    arrival_service_seconds: int | None
    departure_time: str | None
    departure_service_seconds: int | None


@dataclass(frozen=True)
class StopInspection:
    """Contexto acotado de una parada y sus eventos programados del feed."""

    stop: StopSummary | None
    service_date: date | None
    routes: PagedResult[RouteSummary]
    services: PagedResult[ServiceSummary]
    scheduled_events: PagedResult[ScheduledStopEvent]
