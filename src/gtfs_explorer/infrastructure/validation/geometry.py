"""Reglas geográficas contextuales para entidades normalizadas de GTFS."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite

from gtfs_explorer.domain.validation import (
    LocalizedMessage,
    ValidationCategory,
    ValidationContext,
    ValidationEntity,
    ValidationIssue,
    ValidationSeverity,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection
from gtfs_explorer.infrastructure.geometry import build_trip_shape_geometry


@dataclass(frozen=True)
class GeometryValidationRule:
    """Valida shapes y distancia parada-shape en el contexto inequívoco de un viaje.

    La distancia no se atribuye a una parada globalmente: una misma parada puede
    aparecer en varios viajes y shapes. Cada aviso identifica por ello el viaje
    concreto que declara el shape.
    """

    connection: DatabaseConnection
    stop_shape_distance_threshold_meters: float = 100.0
    code: str = "GTFS_GEOMETRY_2026_04_27"
    severity: ValidationSeverity = ValidationSeverity.ERROR
    category: ValidationCategory = ValidationCategory.GEOMETRY

    def __post_init__(self) -> None:
        if self.stop_shape_distance_threshold_meters <= 0:
            raise ValueError("El umbral parada-shape debe ser positivo.")

    def evaluate(self, _context: ValidationContext) -> Iterable[ValidationIssue]:
        shape_rows = self._shape_rows()
        yield from _shape_issues(shape_rows)
        yield from self._duplicate_sequence_issues()
        for trip_id, shape_id, stop_rows in self._trip_stop_rows():
            geometry = build_trip_shape_geometry(
                trip_id, shape_id, shape_rows.get(shape_id, ()), stop_rows
            )
            for issue in geometry.issues:
                yield _issue(
                    "GTFS_SHAPE_GEOMETRY_INVALID",
                    ValidationSeverity.ERROR,
                    "validation.shape_geometry_invalid",
                    "shapes.txt",
                    None,
                    "shape_id",
                    trip_id,
                    {"shape_id": shape_id or "", "detail": issue.code},
                )
            for distance in geometry.stop_distances:
                if (
                    distance.distance_meters is not None
                    and distance.distance_meters > self.stop_shape_distance_threshold_meters
                ):
                    yield _issue(
                        "GTFS_STOP_SHAPE_DISTANCE_EXCEEDS_THRESHOLD",
                        ValidationSeverity.WARNING,
                        "validation.stop_shape_distance_exceeds_threshold",
                        "stop_times.txt",
                        None,
                        "stop_id",
                        trip_id,
                        {
                            "distance_meters": round(distance.distance_meters, 3),
                            "method": geometry.distance_method,
                            "shape_id": shape_id or "",
                            "stop_id": distance.stop_id or "",
                            "threshold_meters": self.stop_shape_distance_threshold_meters,
                            "unit": geometry.distance_unit,
                        },
                    )

    def _shape_rows(self) -> dict[str | None, tuple[tuple[object, object, object], ...]]:
        rows_by_shape: dict[str | None, list[tuple[object, object, object]]] = defaultdict(list)
        for source_row, shape_id, latitude, longitude in self.connection.execute(
            "SELECT source_row, shape_id, shape_pt_lat, shape_pt_lon FROM gtfs_shapes "
            "ORDER BY shape_id, shape_pt_sequence NULLS LAST, source_row"
        ).fetchall():
            rows_by_shape[str(shape_id) if shape_id is not None else None].append(
                (source_row, latitude, longitude)
            )
        return {shape_id: tuple(rows) for shape_id, rows in rows_by_shape.items()}

    def _trip_stop_rows(
        self,
    ) -> Iterable[tuple[str, str | None, tuple[tuple[object, object, object], ...]]]:
        rows: dict[tuple[str, str | None], list[tuple[object, object, object]]] = defaultdict(list)
        query = """
            SELECT trip.trip_id, trip.shape_id, stop.stop_id, stop.stop_lat, stop.stop_lon
            FROM gtfs_trips trip
            JOIN gtfs_stop_times stop_time ON stop_time.trip_id = trip.trip_id
            JOIN gtfs_stops stop ON stop.stop_id = stop_time.stop_id
            WHERE trip.trip_id IS NOT NULL
            ORDER BY trip.trip_id, stop_time.stop_sequence, stop_time.source_row
        """
        result_rows = self.connection.execute(query).fetchall()
        for trip_id, shape_id, stop_id, latitude, longitude in result_rows:
            rows[(str(trip_id), str(shape_id) if shape_id is not None else None)].append(
                (stop_id, latitude, longitude)
            )
        for (trip_id, shape_id), stop_rows in rows.items():
            yield trip_id, shape_id, tuple(stop_rows)

    def _duplicate_sequence_issues(self) -> Iterable[ValidationIssue]:
        query = """
            SELECT shape_id, shape_pt_sequence, min(source_row)
            FROM gtfs_shapes
            WHERE shape_id IS NOT NULL AND shape_pt_sequence IS NOT NULL
            GROUP BY shape_id, shape_pt_sequence
            HAVING count(*) > 1
            ORDER BY shape_id, shape_pt_sequence
        """
        for shape_id, sequence, source_row in self.connection.execute(query).fetchall():
            yield _issue(
                "GTFS_SHAPE_SEQUENCE_DUPLICATED",
                ValidationSeverity.ERROR,
                "validation.shape_sequence_duplicated",
                "shapes.txt",
                _row_number(source_row),
                "shape_pt_sequence",
                str(shape_id),
                {"shape_id": str(shape_id), "sequence": str(sequence)},
            )


def _shape_issues(
    shape_rows: dict[str | None, tuple[tuple[object, object, object], ...]],
) -> Iterable[ValidationIssue]:
    for shape_id, rows in shape_rows.items():
        coordinates = {
            coordinate
            for _, latitude, longitude in rows
            if (coordinate := _coordinate(latitude, longitude)) is not None
        }
        if len(coordinates) < 2:
            yield _issue(
                "GTFS_SHAPE_DEGENERATE",
                ValidationSeverity.ERROR,
                "validation.shape_degenerate",
                "shapes.txt",
                _row_number(rows[0][0]) if rows else None,
                "shape_id",
                shape_id or "",
                {"shape_id": shape_id or "", "method": "WGS84", "unit": "degrees"},
            )


def _coordinate(latitude: object, longitude: object) -> tuple[float, float] | None:
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return None
    lat, lon = float(latitude), float(longitude)
    if not isfinite(lat) or not isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return lat, lon


def _row_number(value: object) -> int:
    if not isinstance(value, (int, float)):
        raise ValueError("La fila geométrica debe ser numérica.")
    return int(value)


def _issue(
    code: str,
    severity: ValidationSeverity,
    message_key: str,
    file_name: str,
    row_number: int | None,
    field_name: str,
    entity_id: str,
    parameters: dict[str, str | float],
) -> ValidationIssue:
    return ValidationIssue(
        rule_code=code,
        severity=severity,
        category=ValidationCategory.GEOMETRY,
        message=LocalizedMessage(message_key, parameters),
        file_name=file_name,
        row_number=row_number,
        field_name=field_name,
        entity=ValidationEntity("trip" if file_name == "stop_times.txt" else "shape", entity_id),
    )
