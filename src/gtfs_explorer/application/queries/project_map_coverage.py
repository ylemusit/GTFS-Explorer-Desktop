"""Cobertura geográfica del feed desde las tablas normalizadas."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite

from gtfs_explorer.infrastructure.maps.offline_library import ProjectMapCoverage

DEFAULT_COVERAGE_MARGIN_DEGREES = 0.02


def project_map_coverage(
    connection: object, *, margin: float = DEFAULT_COVERAGE_MARGIN_DEGREES
) -> ProjectMapCoverage:
    """Prefiere shapes y usa stops como fallback, sin releer ZIP/RAW.

    El margen es una regla única de producto para que un borde cartográfico no
    descarte un paquete útil por pocos metros.
    """
    if margin < 0:
        raise ValueError("El margen de cobertura no puede ser negativo.")
    shapes = _bounds(connection, "SELECT shape_pt_lon, shape_pt_lat FROM gtfs_shapes")
    if shapes is not None:
        return ProjectMapCoverage(_expand(shapes, margin), "shapes")
    stops = _bounds(connection, "SELECT stop_lon, stop_lat FROM gtfs_stops")
    return ProjectMapCoverage(_expand(stops, margin) if stops else None, "stops" if stops else None)


def route_map_coverage(
    connection: object, route_id: str, *, margin: float = DEFAULT_COVERAGE_MARGIN_DEGREES
) -> ProjectMapCoverage:
    """Calcula la extensión conjunta de todos los shapes de una ruta.

    Si la ruta no tiene shapes válidos, usa las paradas de todos sus viajes.
    """
    if margin < 0:
        raise ValueError("El margen de cobertura no puede ser negativo.")
    shapes = _bounds(
        connection,
        "SELECT s.shape_pt_lon, s.shape_pt_lat FROM gtfs_shapes s "
        "JOIN (SELECT DISTINCT shape_id FROM gtfs_trips WHERE route_id = ? "
        "AND shape_id IS NOT NULL) t ON t.shape_id = s.shape_id",
        [route_id],
    )
    if shapes is not None:
        return ProjectMapCoverage(_expand(shapes, margin), "route_shapes")
    stops = _bounds(
        connection,
        "SELECT s.stop_lon, s.stop_lat FROM gtfs_stops s "
        "JOIN gtfs_stop_times st ON st.stop_id = s.stop_id "
        "JOIN gtfs_trips t ON t.trip_id = st.trip_id WHERE t.route_id = ?",
        [route_id],
    )
    return ProjectMapCoverage(
        _expand(stops, margin) if stops else None, "route_stops" if stops else None
    )


def _bounds(
    connection: object, query: str, parameters: Sequence[object] = ()
) -> tuple[float, float, float, float] | None:
    rows: Sequence[Sequence[object]] = connection.execute(query, list(parameters)).fetchall()  # type: ignore[attr-defined]
    points = [
        (float(row[0]), float(row[1]))
        for row in rows
        if len(row) >= 2
        and isinstance(row[0], (int, float))
        and isinstance(row[1], (int, float))
        and isfinite(float(row[0]))
        and isfinite(float(row[1]))
        and -180 <= float(row[0]) <= 180
        and -90 <= float(row[1]) <= 90
    ]
    if not points:
        return None
    longitudes, latitudes = zip(*points)
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def _expand(
    bounds: tuple[float, float, float, float], margin: float
) -> tuple[float, float, float, float]:
    west, south, east, north = bounds
    return (
        max(-180, west - margin),
        max(-90, south - margin),
        min(180, east + margin),
        min(90, north + margin),
    )
