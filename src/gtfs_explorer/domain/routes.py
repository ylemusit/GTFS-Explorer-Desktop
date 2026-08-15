"""Datos de exploración relacional de un feed GTFS Schedule."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteSummary:
    route_id: str
    agency_id: str | None
    short_name: str | None
    long_name: str | None
    route_type: int | None


@dataclass(frozen=True)
class ServiceSummary:
    service_id: str
    trip_count: int


@dataclass(frozen=True)
class DirectionSummary:
    """Dirección declarada por GTFS, incluido el valor ausente."""

    direction_id: int | None
    trip_count: int


@dataclass(frozen=True)
class TripSummary:
    trip_id: str
    route_id: str
    service_id: str
    direction_id: int | None
    headsign: str | None
    short_name: str | None
    shape_id: str | None


@dataclass(frozen=True)
class TimelineStop:
    stop_sequence: int | None
    stop_id: str | None
    stop_name: str | None
    arrival_time: str | None
    arrival_service_seconds: int | None
    departure_time: str | None
    departure_service_seconds: int | None
