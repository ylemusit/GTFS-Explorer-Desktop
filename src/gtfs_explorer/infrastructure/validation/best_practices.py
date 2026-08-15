"""Recomendaciones locales separadas de la validez formal de un feed."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from gtfs_explorer.domain.validation import (
    LocalizedMessage,
    ValidationCategory,
    ValidationContext,
    ValidationEntity,
    ValidationIssue,
    ValidationSeverity,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection


@dataclass(frozen=True)
class BestPracticeValidationRule:
    """Emite recomendaciones documentadas, nunca errores de validez GTFS.

    El subconjunto inicial se limita deliberadamente a relaciones que ya están
    normalizadas: rutas y paradas sin uso, y viajes sin geometría declarada.
    """

    connection: DatabaseConnection
    code: str = "GTFS_BEST_PRACTICES_2026_04_27"
    severity: ValidationSeverity = ValidationSeverity.NOTICE
    category: ValidationCategory = ValidationCategory.BEST_PRACTICE

    def evaluate(self, _context: ValidationContext) -> Iterable[ValidationIssue]:
        yield from self._unused_routes()
        yield from self._unused_stops()
        yield from self._trips_without_shape()

    def _unused_routes(self) -> Iterable[ValidationIssue]:
        query = """
            SELECT route.source_row, route.route_id
            FROM gtfs_routes route
            LEFT JOIN gtfs_trips trip ON trip.route_id = route.route_id
            WHERE route.route_id IS NOT NULL AND trip.trip_id IS NULL
            ORDER BY route.route_id, route.source_row
        """
        for source_row, route_id in self.connection.execute(query).fetchall():
            yield _issue(
                "GTFS_BP_ROUTE_WITHOUT_TRIPS",
                "validation.best_practice_route_without_trips",
                "routes.txt",
                int(source_row),
                "route_id",
                "route",
                str(route_id),
            )

    def _unused_stops(self) -> Iterable[ValidationIssue]:
        query = """
            SELECT stop.source_row, stop.stop_id
            FROM gtfs_stops stop
            LEFT JOIN gtfs_stop_times stop_time ON stop_time.stop_id = stop.stop_id
            WHERE stop.stop_id IS NOT NULL
              AND coalesce(stop.location_type, 0) = 0
              AND stop_time.trip_id IS NULL
            ORDER BY stop.stop_id, stop.source_row
        """
        for source_row, stop_id in self.connection.execute(query).fetchall():
            yield _issue(
                "GTFS_BP_STOP_WITHOUT_STOP_TIMES",
                "validation.best_practice_stop_without_stop_times",
                "stops.txt",
                int(source_row),
                "stop_id",
                "stop",
                str(stop_id),
            )

    def _trips_without_shape(self) -> Iterable[ValidationIssue]:
        query = """
            SELECT source_row, trip_id
            FROM gtfs_trips
            WHERE trip_id IS NOT NULL AND (shape_id IS NULL OR shape_id = '')
            ORDER BY trip_id, source_row
        """
        for source_row, trip_id in self.connection.execute(query).fetchall():
            yield _issue(
                "GTFS_BP_TRIP_WITHOUT_SHAPE",
                "validation.best_practice_trip_without_shape",
                "trips.txt",
                int(source_row),
                "shape_id",
                "trip",
                str(trip_id),
            )


def _issue(
    rule_code: str,
    message_key: str,
    file_name: str,
    row_number: int,
    field_name: str,
    entity_type: str,
    entity_id: str,
) -> ValidationIssue:
    return ValidationIssue(
        rule_code=rule_code,
        severity=ValidationSeverity.NOTICE,
        category=ValidationCategory.BEST_PRACTICE,
        message=LocalizedMessage(message_key, {"origin": "gtfs-explorer/best-practice"}),
        file_name=file_name,
        row_number=row_number,
        field_name=field_name,
        entity=ValidationEntity(entity_type, entity_id),
    )
