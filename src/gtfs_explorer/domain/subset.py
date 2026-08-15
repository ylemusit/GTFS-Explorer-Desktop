"""Cierre transitivo puro para el subconjunto core Mini-GTFS."""

from __future__ import annotations

from dataclasses import dataclass


class SubsetSelectionError(ValueError):
    """La selección no identifica un subconjunto core exportable."""


class SubsetIntegrityError(ValueError):
    """El cierre no puede conservar las referencias core requeridas."""


@dataclass(frozen=True)
class SubsetSelection:
    """Rutas y restricciones opcionales autorizadas para Mini-GTFS."""

    route_ids: frozenset[str]
    trip_ids: frozenset[str] | None = None
    service_ids: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if not self.route_ids:
            raise SubsetSelectionError("Debe seleccionarse al menos una ruta para Mini-GTFS.")
        if self.trip_ids is not None and not self.trip_ids:
            raise SubsetSelectionError("La restricción de viajes no puede estar vacía.")
        if self.service_ids is not None and not self.service_ids:
            raise SubsetSelectionError("La restricción de servicios no puede estar vacía.")


@dataclass(frozen=True)
class CoreTrip:
    trip_id: str
    route_id: str
    service_id: str


@dataclass(frozen=True)
class CoreStop:
    stop_id: str
    parent_station: str | None


@dataclass(frozen=True)
class CoreSubsetSource:
    """Relaciones core necesarias; no conoce SQL ni archivos de salida."""

    route_agencies: tuple[tuple[str, str | None], ...]
    trips: tuple[CoreTrip, ...]
    stop_times: tuple[tuple[str, str], ...]
    stops: tuple[CoreStop, ...]
    calendar_service_ids: frozenset[str]
    calendar_date_service_ids: frozenset[str]
    agency_ids: frozenset[str]


@dataclass(frozen=True)
class InclusionReport:
    """Evidencia compacta de las entidades que justifican la inclusión."""

    counts: tuple[tuple[str, int], ...]

    def count(self, entity_type: str) -> int:
        return dict(self.counts).get(entity_type, 0)


@dataclass(frozen=True)
class CoreSubset:
    route_ids: frozenset[str]
    trip_ids: frozenset[str]
    stop_ids: frozenset[str]
    service_ids: frozenset[str]
    calendar_service_ids: frozenset[str]
    calendar_date_service_ids: frozenset[str]
    agency_ids: frozenset[str]
    report: InclusionReport


def close_core_subset(source: CoreSubsetSource, selection: SubsetSelection) -> CoreSubset:
    """Calcula los pasos 1--7 del cierre sin escribir ni modificar el feed."""
    route_agencies = dict(source.route_agencies)
    unknown_routes = selection.route_ids - route_agencies.keys()
    if unknown_routes:
        raise SubsetSelectionError(_unknown("rutas", unknown_routes))

    selected_trips = tuple(
        trip
        for trip in source.trips
        if trip.route_id in selection.route_ids
        and (selection.trip_ids is None or trip.trip_id in selection.trip_ids)
        and (selection.service_ids is None or trip.service_id in selection.service_ids)
    )
    if not selected_trips:
        raise SubsetSelectionError("La selección no deja ningún viaje para las rutas indicadas.")
    if selection.trip_ids is not None:
        missing_trips = selection.trip_ids - {trip.trip_id for trip in selected_trips}
        if missing_trips:
            raise SubsetSelectionError(
                _unknown("viajes compatibles con la selección", missing_trips)
            )
    if selection.service_ids is not None:
        missing_services = selection.service_ids - {trip.service_id for trip in selected_trips}
        if missing_services:
            raise SubsetSelectionError(
                _unknown("servicios compatibles con la selección", missing_services)
            )

    trip_ids = frozenset(trip.trip_id for trip in selected_trips)
    service_ids = frozenset(trip.service_id for trip in selected_trips)
    stop_ids = _close_stops(source, trip_ids)
    calendar_ids = service_ids & source.calendar_service_ids
    calendar_date_ids = service_ids & source.calendar_date_service_ids
    missing_calendar = service_ids - calendar_ids - calendar_date_ids
    if missing_calendar:
        raise SubsetIntegrityError(
            _unknown("servicios sin calendar.txt ni calendar_dates.txt", missing_calendar)
        )
    agency_ids = _close_agencies(route_agencies, selection.route_ids, source.agency_ids)
    return CoreSubset(
        route_ids=selection.route_ids,
        trip_ids=trip_ids,
        stop_ids=stop_ids,
        service_ids=service_ids,
        calendar_service_ids=calendar_ids,
        calendar_date_service_ids=calendar_date_ids,
        agency_ids=agency_ids,
        report=InclusionReport(
            tuple(
                (name, len(values))
                for name, values in (
                    ("agency", agency_ids),
                    ("route", selection.route_ids),
                    ("trip", trip_ids),
                    ("stop", stop_ids),
                    ("service", service_ids),
                    ("calendar", calendar_ids),
                    ("calendar_date", calendar_date_ids),
                )
            )
        ),
    )


def _close_stops(source: CoreSubsetSource, trip_ids: frozenset[str]) -> frozenset[str]:
    by_trip: dict[str, set[str]] = {}
    for trip_id, stop_id in source.stop_times:
        by_trip.setdefault(trip_id, set()).add(stop_id)
    missing_stop_times = trip_ids - by_trip.keys()
    if missing_stop_times:
        raise SubsetIntegrityError(_unknown("viajes sin stop_times", missing_stop_times))
    stops = {stop.stop_id: stop.parent_station for stop in source.stops}
    included = set().union(*(by_trip[trip_id] for trip_id in trip_ids))
    pending = list(included)
    while pending:
        stop_id = pending.pop()
        parent = stops.get(stop_id)
        if stop_id not in stops:
            raise SubsetIntegrityError(_unknown("paradas ausentes", {stop_id}))
        if parent is not None and parent not in included:
            included.add(parent)
            pending.append(parent)
    return frozenset(included)


def _close_agencies(
    route_agencies: dict[str, str | None], route_ids: frozenset[str], agency_ids: frozenset[str]
) -> frozenset[str]:
    selected: set[str] = set()
    for route_id in route_ids:
        agency_id = route_agencies[route_id]
        if agency_id is not None:
            selected.add(agency_id)
    if any(route_agencies[route_id] is None for route_id in route_ids):
        if len(agency_ids) != 1:
            raise SubsetIntegrityError("Una ruta sin agency_id es ambigua en un feed multiagencia.")
        selected.update(agency_ids)
    missing = selected - agency_ids
    if missing:
        raise SubsetIntegrityError(_unknown("agencias ausentes", missing))
    return frozenset(selected)


def _unknown(subject: str, values: set[str] | frozenset[str]) -> str:
    return f"No se han encontrado {subject}: {', '.join(sorted(values))}."
