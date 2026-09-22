"""Semántica condicional de ``trips.shape_id`` según GTFS Schedule."""

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

_CONDITIONAL_SHAPE_SQL = """
    SELECT DISTINCT trip.source_row, trip.trip_id
    FROM gtfs_trips trip
    LEFT JOIN gtfs_routes route ON route.route_id = trip.route_id
    LEFT JOIN gtfs_stop_times stop_time ON stop_time.trip_id = trip.trip_id
    WHERE trip.trip_id IS NOT NULL AND (trip.shape_id IS NULL OR trip.shape_id = '')
      AND (
        coalesce(route.continuous_pickup, 1) IN (0, 2, 3)
        OR coalesce(route.continuous_drop_off, 1) IN (0, 2, 3)
        OR coalesce(stop_time.continuous_pickup, 1) IN (0, 2, 3)
        OR coalesce(stop_time.continuous_drop_off, 1) IN (0, 2, 3)
      )
    ORDER BY trip.trip_id, trip.source_row
"""


@dataclass(frozen=True)
class ShapeRequirementValidationRule:
    connection: DatabaseConnection
    code: str = "GTFS_TRIPS_TXT_SHAPE_ID_CONDITIONALLY_REQUIRED"
    severity: ValidationSeverity = ValidationSeverity.ERROR
    category: ValidationCategory = ValidationCategory.FIELD

    def evaluate(self, _context: ValidationContext) -> Iterable[ValidationIssue]:
        for source_row, trip_id in self.connection.execute(_CONDITIONAL_SHAPE_SQL).fetchall():
            yield ValidationIssue(
                rule_code=self.code,
                severity=self.severity,
                category=self.category,
                message=LocalizedMessage(
                    "validation.required_value_missing", {"field": "shape_id"}
                ),
                file_name="trips.txt",
                row_number=int(source_row),
                field_name="shape_id",
                entity=ValidationEntity("trip", str(trip_id)),
            )


def optional_shape_trip_rows(connection: DatabaseConnection) -> Iterable[tuple[object, object]]:
    return connection.execute(
        "SELECT trip.source_row, trip.trip_id FROM gtfs_trips trip "
        "LEFT JOIN gtfs_routes route ON route.route_id = trip.route_id "
        "WHERE trip.trip_id IS NOT NULL AND (trip.shape_id IS NULL OR trip.shape_id = '') "
        "AND coalesce(route.continuous_pickup, 1) NOT IN (0, 2, 3) "
        "AND coalesce(route.continuous_drop_off, 1) NOT IN (0, 2, 3) "
        "AND NOT EXISTS (SELECT 1 FROM gtfs_stop_times stop_time "
        "WHERE stop_time.trip_id = trip.trip_id AND ("
        "coalesce(stop_time.continuous_pickup, 1) IN (0, 2, 3) OR "
        "coalesce(stop_time.continuous_drop_off, 1) IN (0, 2, 3))) "
        "ORDER BY trip.trip_id, trip.source_row"
    ).fetchall()
