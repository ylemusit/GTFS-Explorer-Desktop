"""Exportación GeoJSON RFC 7946 de paradas y shapes GTFS."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gtfs_explorer.domain.exporting import ExportManifest
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection
from gtfs_explorer.infrastructure.exporting.atomic_output import (
    AtomicOutputWriter,
    CancellationCheck,
)

_BATCH_SIZE = 1_000


@dataclass(frozen=True)
class GeoJsonExportSelection:
    """La selección explícita que acota las entidades incluidas en GeoJSON."""

    route_ids: frozenset[str]
    trip_ids: frozenset[str] = frozenset()
    service_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.route_ids:
            raise ValueError("La exportación GeoJSON requiere al menos una ruta seleccionada.")
        if any(not value for value in (*self.route_ids, *self.trip_ids, *self.service_ids)):
            raise ValueError("Los identificadores de selección no pueden estar vacíos.")


class GeoJsonExporter:
    """Publica un FeatureCollection sin coordenadas fuera de RFC 7946."""

    def __init__(self, writer: AtomicOutputWriter | None = None) -> None:
        self._writer = writer or AtomicOutputWriter()

    def write(
        self,
        connection: DatabaseConnection,
        destination: Path,
        *,
        selection: GeoJsonExportSelection,
        overwrite: bool = False,
        include_bbox: bool = False,
        is_cancelled: CancellationCheck = lambda: False,
    ) -> ExportManifest:
        predicate, parameters = _trip_predicate(selection)
        return self._writer.write(
            destination,
            self._chunks(connection, predicate, parameters, include_bbox, is_cancelled),
            overwrite=overwrite,
            is_cancelled=is_cancelled,
        )

    def _chunks(
        self,
        connection: DatabaseConnection,
        predicate: str,
        parameters: list[str],
        include_bbox: bool,
        is_cancelled: CancellationCheck,
    ) -> Iterator[bytes]:
        features = self._features(connection, predicate, parameters, is_cancelled)
        yield b'{"type":"FeatureCollection","features":['
        first = True
        bounds: list[float] | None = None
        for feature in features:
            if is_cancelled():
                from gtfs_explorer.domain.exporting import ExportCancelled

                raise ExportCancelled("La exportación se ha cancelado.")
            if include_bbox:
                bounds = _extend_bounds(bounds, _geometry_coordinates(feature))
            prefix = b"" if first else b","
            yield prefix + _dump(feature).encode("utf-8")
            first = False
        yield b"]"
        if bounds is not None:
            yield b',"bbox":' + _dump(bounds).encode("utf-8")
        yield b"}\n"

    def _features(
        self,
        connection: DatabaseConnection,
        predicate: str,
        parameters: list[str],
        is_cancelled: CancellationCheck,
    ) -> Iterator[dict[str, object]]:
        stop_query = (
            "SELECT DISTINCT s.stop_id, s.stop_name, s.stop_lat, s.stop_lon, "
            "s.source_filename, s.source_row FROM gtfs_stops s "
            "JOIN gtfs_stop_times st ON st.stop_id = s.stop_id "
            "JOIN gtfs_trips t ON t.trip_id = st.trip_id WHERE "
            + predicate
            + " ORDER BY s.stop_id, s.source_row"
        )
        for row in _rows(connection, stop_query, parameters):
            coordinate = _coordinate(row["stop_lon"], row["stop_lat"])
            if coordinate is None:
                continue
            yield {
                "type": "Feature",
                "properties": {
                    "feature_kind": "stop",
                    "stop_id": row["stop_id"],
                    "stop_name": row["stop_name"],
                    "source_file": row["source_filename"],
                    "source_row": row["source_row"],
                },
                "geometry": {"type": "Point", "coordinates": coordinate},
            }

        shape_query = (
            "SELECT DISTINCT sh.shape_id, sh.shape_pt_lon, sh.shape_pt_lat, sh.shape_pt_sequence, "
            "sh.source_filename, sh.source_row FROM gtfs_shapes sh "
            "JOIN gtfs_trips t ON t.shape_id = sh.shape_id WHERE "
            + predicate
            + " ORDER BY sh.shape_id, sh.shape_pt_sequence, sh.source_row"
        )
        shape_id: str | None = None
        coordinates: list[list[float]] = []
        source_file: object = None
        source_row: object = None
        for row in _rows(connection, shape_query, parameters):
            current_id = _string_or_none(row["shape_id"])
            if current_id != shape_id:
                if shape_id is not None:
                    yield from _shape_feature(shape_id, coordinates, source_file, source_row)
                shape_id, coordinates = current_id, []
                source_file, source_row = row["source_filename"], row["source_row"]
            coordinate = _coordinate(row["shape_pt_lon"], row["shape_pt_lat"])
            if coordinate is not None:
                coordinates.append(coordinate)
            if is_cancelled():
                from gtfs_explorer.domain.exporting import ExportCancelled

                raise ExportCancelled("La exportación se ha cancelado.")
        if shape_id is not None:
            yield from _shape_feature(shape_id, coordinates, source_file, source_row)


def _trip_predicate(selection: GeoJsonExportSelection) -> tuple[str, list[str]]:
    conditions = [_in("t.route_id", selection.route_ids)]
    parameters = sorted(selection.route_ids)
    if selection.trip_ids:
        conditions.append(_in("t.trip_id", selection.trip_ids))
        parameters.extend(sorted(selection.trip_ids))
    if selection.service_ids:
        conditions.append(_in("t.service_id", selection.service_ids))
        parameters.extend(sorted(selection.service_ids))
    return " AND ".join(conditions), parameters


def _in(column: str, values: frozenset[str]) -> str:
    return f"{column} IN ({', '.join('?' for _ in values)})"


def _rows(
    connection: DatabaseConnection, query: str, parameters: list[str]
) -> Iterator[dict[str, Any]]:
    cursor = connection.execute(query, parameters)
    columns = [str(item[0]) for item in cursor.description or ()]
    while batch := cursor.fetchmany(_BATCH_SIZE):
        yield from (dict(zip(columns, row, strict=True)) for row in batch)


def _coordinate(longitude: object, latitude: object) -> list[float] | None:
    if not isinstance(longitude, (int, float)) or not isinstance(latitude, (int, float)):
        return None
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        return None
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        return None
    return [float(longitude), float(latitude)]


def _shape_feature(
    shape_id: str, coordinates: list[list[float]], source_file: object, source_row: object
) -> Iterator[dict[str, object]]:
    if len(coordinates) < 2:
        return
    yield {
        "type": "Feature",
        "properties": {
            "feature_kind": "shape",
            "shape_id": shape_id,
            "geometry_source": "original",
            "source_file": source_file,
            "source_row": source_row,
        },
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


def _extend_bounds(bounds: list[float] | None, coordinates: object) -> list[float] | None:
    points = _points(coordinates)
    if not points:
        return bounds
    west, south = min(point[0] for point in points), min(point[1] for point in points)
    east, north = max(point[0] for point in points), max(point[1] for point in points)
    if bounds is None:
        return [west, south, east, north]
    return [
        min(bounds[0], west),
        min(bounds[1], south),
        max(bounds[2], east),
        max(bounds[3], north),
    ]


def _geometry_coordinates(feature: dict[str, object]) -> object:
    geometry = feature["geometry"]
    if not isinstance(geometry, dict):
        return None
    return geometry.get("coordinates")


def _points(coordinates: object) -> list[list[float]]:
    if (
        isinstance(coordinates, list)
        and len(coordinates) == 2
        and all(isinstance(value, float) for value in coordinates)
    ):
        return [coordinates]
    if isinstance(coordinates, list):
        return [point for item in coordinates for point in _points(item)]
    return []


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
