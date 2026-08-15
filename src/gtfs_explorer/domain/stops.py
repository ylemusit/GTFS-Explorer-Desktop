"""Datos del inspector de paradas de un feed GTFS Schedule."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from .routes import RouteSummary, ServiceSummary

if TYPE_CHECKING:
    from .ports import PagedResult


@dataclass(frozen=True)
class StopSummary:
    stop_id: str
    name: str | None
    parent_station: str | None


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
