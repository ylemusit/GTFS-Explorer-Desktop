"""Construcción de métricas WGS84 con distancias expresadas en metros."""

from __future__ import annotations

from math import acos, atan2, cos, isfinite, radians, sin, sqrt
from typing import Iterable

from gtfs_explorer.domain.geometry import (
    BoundingBox,
    Coordinate,
    GeometryIssue,
    MapStop,
    StopShapeDistance,
    TripShapeGeometry,
)

_EARTH_RADIUS_METERS = 6_371_008.8
_LENGTH_METHOD = "haversine_spherical_geodesic"
_DISTANCE_METHOD = "local_azimuthal_equidistant_projection"


def build_trip_shape_geometry(
    trip_id: str,
    shape_id: str | None,
    shape_rows: Iterable[tuple[object, object, object]],
    stop_rows: Iterable[tuple[object, object, object]],
    *,
    map_stops: Iterable[tuple[object, ...]] = (),
    route_color: str | None = None,
    route_text_color: str | None = None,
    route_id: str | None = None,
) -> TripShapeGeometry:
    """Construye línea, bbox y distancias sin propagar errores de geometría almacenada."""
    issues: list[GeometryIssue] = []
    points = _valid_points(shape_rows, "SHAPE_COORDINATE_INVALID", issues)
    stops = _valid_stops(stop_rows, issues)
    if shape_id is None:
        issues.append(GeometryIssue("TRIP_SHAPE_MISSING", "El viaje no declara ningún shape."))
    elif not points:
        issues.append(
            GeometryIssue(
                "SHAPE_POINTS_MISSING", "El shape asociado no tiene puntos válidos.", shape_id
            )
        )
    elif len(points) == 1:
        issues.append(
            GeometryIssue(
                "SHAPE_TOO_SHORT", "El shape necesita al menos dos puntos válidos.", shape_id
            )
        )

    is_line = len(points) >= 2
    distances = tuple(
        StopShapeDistance(stop_id, _distance_to_line(coordinate, points) if is_line else None)
        for stop_id, coordinate in stops
    )
    return TripShapeGeometry(
        trip_id=trip_id,
        shape_id=shape_id,
        coordinates=tuple(points),
        length_meters=_line_length(points) if is_line else None,
        bbox=_bounding_box(points) if points else None,
        stop_distances=distances,
        distance_unit="meters",
        length_method=_LENGTH_METHOD,
        distance_method=_DISTANCE_METHOD,
        issues=tuple(issues),
        stops=tuple(
            MapStop(
                str(row[0]),
                str(row[1]) if row[1] is not None else None,
                coordinate,
                int(row[4]) if len(row) > 4 and isinstance(row[4], int) else None,
            )
            for row in map_stops
            if len(row) >= 4
            for stop_id, name, latitude, longitude in [row[:4]]
            if stop_id is not None
            if (coordinate := _coordinate(latitude, longitude)) is not None
        ),
        route_color=route_color,
        route_text_color=route_text_color,
        route_id=route_id,
    )


def _valid_points(
    rows: Iterable[tuple[object, object, object]], code: str, issues: list[GeometryIssue]
) -> list[Coordinate]:
    points: list[Coordinate] = []
    for source_id, latitude, longitude in rows:
        coordinate = _coordinate(latitude, longitude)
        if coordinate is None:
            issues.append(
                GeometryIssue(code, "Coordenada WGS84 inválida; se omite.", _source_id(source_id))
            )
        else:
            points.append(coordinate)
    return points


def _valid_stops(
    rows: Iterable[tuple[object, object, object]], issues: list[GeometryIssue]
) -> list[tuple[str | None, Coordinate]]:
    stops: list[tuple[str | None, Coordinate]] = []
    for stop_id, latitude, longitude in rows:
        coordinate = _coordinate(latitude, longitude)
        if coordinate is None:
            issues.append(
                GeometryIssue(
                    "STOP_COORDINATE_INVALID",
                    "Coordenada de parada WGS84 inválida; se omite.",
                    _source_id(stop_id),
                )
            )
        else:
            stops.append((_source_id(stop_id), coordinate))
    return stops


def _coordinate(latitude: object, longitude: object) -> Coordinate | None:
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return None
    lat = float(latitude)
    lon = float(longitude)
    if not isfinite(lat) or not isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return Coordinate(lat, lon)


def _source_id(value: object) -> str | None:
    return str(value) if value is not None else None


def _line_length(points: list[Coordinate]) -> float:
    return sum(_haversine(start, end) for start, end in zip(points, points[1:], strict=False))


def _haversine(start: Coordinate, end: Coordinate) -> float:
    latitude_delta = radians(end.latitude - start.latitude)
    longitude_delta = radians(_longitude_delta(end.longitude - start.longitude))
    latitude_start = radians(start.latitude)
    latitude_end = radians(end.latitude)
    half_chord = (
        sin(latitude_delta / 2) ** 2
        + cos(latitude_start) * cos(latitude_end) * sin(longitude_delta / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_METERS * atan2(sqrt(half_chord), sqrt(max(0.0, 1 - half_chord)))


def _distance_to_line(stop: Coordinate, points: list[Coordinate]) -> float:
    projected = [_project_aeqd(stop, point) for point in points]
    return min(
        _distance_to_segment((0.0, 0.0), start, end)
        for start, end in zip(projected, projected[1:], strict=False)
    )


def _project_aeqd(center: Coordinate, point: Coordinate) -> tuple[float, float]:
    center_latitude = radians(center.latitude)
    latitude = radians(point.latitude)
    longitude_delta = radians(_longitude_delta(point.longitude - center.longitude))
    cosine_angle = max(
        -1.0,
        min(
            1.0,
            sin(center_latitude) * sin(latitude)
            + cos(center_latitude) * cos(latitude) * cos(longitude_delta),
        ),
    )
    angle = acos(cosine_angle)
    scale = 1.0 if angle == 0 else angle / sin(angle)
    return (
        _EARTH_RADIUS_METERS * scale * cos(latitude) * sin(longitude_delta),
        _EARTH_RADIUS_METERS
        * scale
        * (
            cos(center_latitude) * sin(latitude)
            - sin(center_latitude) * cos(latitude) * cos(longitude_delta)
        ),
    )


def _distance_to_segment(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    delta_x, delta_y = end[0] - start[0], end[1] - start[1]
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0:
        return sqrt((point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2)
    ratio = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * delta_x + (point[1] - start[1]) * delta_y) / length_squared,
        ),
    )
    nearest_x, nearest_y = start[0] + ratio * delta_x, start[1] + ratio * delta_y
    return sqrt((point[0] - nearest_x) ** 2 + (point[1] - nearest_y) ** 2)


def _bounding_box(points: list[Coordinate]) -> BoundingBox:
    longitudes = sorted(point.longitude for point in points)
    gaps = [
        (longitudes[(index + 1) % len(longitudes)] - longitude) % 360
        for index, longitude in enumerate(longitudes)
    ]
    largest_gap_index = max(range(len(gaps)), key=gaps.__getitem__)
    west = longitudes[(largest_gap_index + 1) % len(longitudes)]
    east = longitudes[largest_gap_index]
    return BoundingBox(
        west=west,
        south=min(point.latitude for point in points),
        east=east,
        north=max(point.latitude for point in points),
        crosses_antimeridian=west > east,
    )


def _longitude_delta(delta: float) -> float:
    return (delta + 180) % 360 - 180
