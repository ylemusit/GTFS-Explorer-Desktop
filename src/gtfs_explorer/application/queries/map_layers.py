"""Adaptador de geometría de viaje a capas GeoJSON locales."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from gtfs_explorer.domain.geometry import TripShapeGeometry

_FALLBACK_COLOR = "#2563eb"
MAX_RENDERED_STOPS = 2_000
MAX_RENDERED_SHAPE_POINTS = 4_000


@dataclass(frozen=True)
class MapLayerPayload:
    """Colecciones RFC 7946 listas para una página local, sin SQL ni HTML."""

    shapes: dict[str, object]
    stops: dict[str, object]


@dataclass(frozen=True)
class MapViewport:
    """Ventana WGS84 solicitada por el mapa; sus límites siempre son finitos."""

    west: float
    south: float
    east: float
    north: float
    zoom: float


def sanitize_route_color(value: str | None) -> str:
    """Normaliza el color GTFS RGB o usa un valor de contraste seguro."""
    if not isinstance(value, str):
        return _FALLBACK_COLOR
    normalized = value.strip().removeprefix("#")
    if len(normalized) != 6 or any(
        character not in "0123456789abcdefABCDEF" for character in normalized
    ):
        return _FALLBACK_COLOR
    return f"#{normalized.upper()}"


def map_layers_for_trip(geometry: TripShapeGeometry) -> MapLayerPayload:
    """Construye capas sin fabricar una línea cuando el shape está ausente."""
    color = sanitize_route_color(geometry.route_color)
    shape_features: list[dict[str, object]] = []
    if len(geometry.coordinates) >= 2:
        shape_features.append(
            {
                "type": "Feature",
                "properties": {
                    "trip_id": geometry.trip_id,
                    "shape_id": geometry.shape_id,
                    "color": color,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [point.longitude, point.latitude] for point in geometry.coordinates
                    ],
                },
            }
        )
    stop_features: list[dict[str, object]] = [
        {
            "type": "Feature",
            "properties": {"id": stop.stop_id, "name": stop.name or "Sin nombre"},
            "geometry": {
                "type": "Point",
                "coordinates": [stop.coordinate.longitude, stop.coordinate.latitude],
            },
        }
        for stop in geometry.stops
    ]
    return MapLayerPayload(_collection(shape_features), _collection(stop_features))


def simplify_for_viewport(payload: MapLayerPayload, viewport: MapViewport) -> MapLayerPayload:
    """Reduce una capa al viewport sin modificar la geometría fuente.

    El límite es deliberadamente visual: la selección detallada sigue usando el
    viaje y la parada originales en las consultas Qt. La llamada es pura para
    poder cachear el resultado por viewport y descartarlo si queda obsoleto.
    """
    if not _valid_viewport(viewport):
        return MapLayerPayload(_collection([]), _collection([]))
    tolerance = max(0.000_002, 0.06 / (2 ** max(viewport.zoom, 0.0)))
    shapes: list[dict[str, object]] = []
    for feature in _features(payload.shapes):
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            continue
        coordinates = _line_coordinates(geometry.get("coordinates"))
        visible = _visible_line(coordinates, viewport)
        if len(visible) < 2:
            continue
        visible = _evenly_sample(visible, MAX_RENDERED_SHAPE_POINTS)
        reduced = _douglas_peucker(visible, tolerance)
        if len(reduced) > MAX_RENDERED_SHAPE_POINTS:
            reduced = _evenly_sample(reduced, MAX_RENDERED_SHAPE_POINTS)
        shapes.append({**feature, "geometry": {**geometry, "coordinates": reduced}})
    stops = [
        feature
        for feature in _features(payload.stops)
        if _point_in_viewport(_point_coordinates(feature), viewport)
    ][:MAX_RENDERED_STOPS]
    return MapLayerPayload(_collection(shapes), _collection(stops))


def _features(collection: dict[str, object]) -> list[dict[str, object]]:
    features = collection.get("features")
    if not isinstance(features, list):
        return []
    return [feature for feature in features if isinstance(feature, dict)]


def _line_coordinates(value: object) -> list[list[float]]:
    if not isinstance(value, list):
        return []
    return [
        point
        for point in value
        if isinstance(point, list)
        and len(point) >= 2
        and all(isinstance(item, (int, float)) for item in point[:2])
    ]


def _point_coordinates(feature: dict[str, object]) -> list[float] | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    return coordinates if isinstance(coordinates, list) and len(coordinates) >= 2 else None


def _valid_viewport(viewport: MapViewport) -> bool:
    return (
        -180 <= viewport.west <= 180
        and -180 <= viewport.east <= 180
        and -90 <= viewport.south <= 90
        and -90 <= viewport.north <= 90
        and viewport.west <= viewport.east
        and viewport.south <= viewport.north
        and viewport.zoom >= 0
    )


def _point_in_viewport(point: list[float] | None, viewport: MapViewport) -> bool:
    return (
        point is not None
        and isinstance(point[0], (int, float))
        and isinstance(point[1], (int, float))
        and viewport.west <= point[0] <= viewport.east
        and viewport.south <= point[1] <= viewport.north
    )


def _visible_line(points: list[list[float]], viewport: MapViewport) -> list[list[float]]:
    visible = [point for point in points if _point_in_viewport(point, viewport)]
    return visible if len(visible) >= 2 else []


def _evenly_sample(points: list[list[float]], limit: int) -> list[list[float]]:
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    return [points[round(index * step)] for index in range(limit)]


def _douglas_peucker(points: list[list[float]], tolerance: float) -> list[list[float]]:
    if len(points) <= 2:
        return points
    # Iterativo: una geometría dentada no puede agotar la pila de Python.
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        first, last = pending.pop()
        start, end = points[first], points[last]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = hypot(dx, dy)
        maximum, index = 0.0, None
        for candidate in range(first + 1, last):
            point = points[candidate]
            distance = (
                abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0]) / length
                if length
                else hypot(point[0] - start[0], point[1] - start[1])
            )
            if distance > maximum:
                maximum, index = distance, candidate
        if index is not None and maximum > tolerance:
            keep.add(index)
            pending.extend(((first, index), (index, last)))
    return [points[index] for index in sorted(keep)]


def _collection(features: list[dict[str, object]]) -> dict[str, object]:
    return {"type": "FeatureCollection", "features": features}
