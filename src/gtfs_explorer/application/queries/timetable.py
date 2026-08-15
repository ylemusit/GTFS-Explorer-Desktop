"""Matriz de horarios GTFS acotada para una selección ruta/servicio/dirección."""

from __future__ import annotations

from dataclasses import dataclass

from gtfs_explorer.domain.ports import PageRequest, RouteExplorerRepository
from gtfs_explorer.domain.routes import TimelineStop, TripSummary


@dataclass(frozen=True)
class TimetableCell:
    """Horario programado de una parada, sin inventar el valor que falta."""

    arrival_time: str | None
    departure_time: str | None


@dataclass(frozen=True)
class TimetableRow:
    """Una ocurrencia de parada en un patrón; una parada puede repetirse en un loop."""

    stop_sequence: int | None
    stop_id: str | None
    stop_name: str | None
    occurrence: int


@dataclass(frozen=True)
class TimetableColumn:
    trip_id: str
    cells: tuple[TimetableCell, ...]


@dataclass(frozen=True)
class TimetablePattern:
    """Viajes comparables que comparten exactamente la secuencia de paradas."""

    rows: tuple[TimetableRow, ...]
    columns: tuple[TimetableColumn, ...]


@dataclass(frozen=True)
class TimetableExportScope:
    """Selección reproducible que una exportación posterior puede resolver completa."""

    route_id: str
    service_id: str
    direction_id: int | None


@dataclass(frozen=True)
class TimetableMatrix:
    route_id: str
    service_id: str
    direction_id: int | None
    patterns: tuple[TimetablePattern, ...]
    total_trips: int
    truncated: bool
    export_scope: TimetableExportScope


class TimetableQueries:
    """Construye una vista previa limitada; nunca carga todos los viajes para mostrarla."""

    DEFAULT_COLUMN_LIMIT = 100
    MAX_COLUMN_LIMIT = 499

    def __init__(self, repository: RouteExplorerRepository) -> None:
        self._repository = repository

    def matrix(
        self,
        route_id: str,
        service_id: str,
        direction_id: int | None,
        *,
        column_limit: int = DEFAULT_COLUMN_LIMIT,
    ) -> TimetableMatrix:
        """Devuelve patrones de hasta ``column_limit`` viajes y el alcance de exportación total.

        El total procede de la consulta paginada de viajes. Así, un feed con miles de
        viajes no obliga a leer sus timelines ni a construir sus celdas para la vista.
        """
        if not 1 <= column_limit <= self.MAX_COLUMN_LIMIT:
            raise ValueError(f"El límite de columnas debe estar entre 1 y {self.MAX_COLUMN_LIMIT}.")

        selected = self._repository.trips_for_route_service_direction(
            route_id, service_id, direction_id, PageRequest(limit=column_limit)
        )
        patterns: dict[tuple[tuple[int | None, str | None], ...], list[_TripTimeline]] = {}
        for trip in selected.items:
            timeline = self._repository.trip_timeline(trip.trip_id, PageRequest(limit=500))
            stops = timeline.items
            signature = tuple((stop.stop_sequence, stop.stop_id) for stop in stops)
            patterns.setdefault(signature, []).append(_TripTimeline(trip, stops))

        return TimetableMatrix(
            route_id=route_id,
            service_id=service_id,
            direction_id=direction_id,
            patterns=tuple(_pattern(trips) for trips in patterns.values()),
            total_trips=selected.total,
            truncated=selected.total > len(selected.items),
            export_scope=TimetableExportScope(route_id, service_id, direction_id),
        )


@dataclass(frozen=True)
class _TripTimeline:
    trip: TripSummary
    stops: tuple[TimelineStop, ...]


def _pattern(trips: list[_TripTimeline]) -> TimetablePattern:
    reference = trips[0].stops
    occurrences: dict[tuple[int | None, str | None], int] = {}
    rows: list[TimetableRow] = []
    for stop in reference:
        key = (stop.stop_sequence, stop.stop_id)
        occurrences[key] = occurrences.get(key, 0) + 1
        rows.append(
            TimetableRow(stop.stop_sequence, stop.stop_id, stop.stop_name, occurrences[key])
        )
    return TimetablePattern(
        rows=tuple(rows),
        columns=tuple(
            TimetableColumn(
                trip.trip.trip_id,
                tuple(TimetableCell(stop.arrival_time, stop.departure_time) for stop in trip.stops),
            )
            for trip in trips
        ),
    )
