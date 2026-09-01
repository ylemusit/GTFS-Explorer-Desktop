"""DTOs de líneas GTFS y métricas geográficas expresadas en metros."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Coordinate:
    """Coordenada WGS84, conservada como latitud y longitud."""

    latitude: float
    longitude: float


@dataclass(frozen=True)
class BoundingBox:
    """Extensión WGS84; ``crosses_antimeridian`` evita una bbox global artificial."""

    west: float
    south: float
    east: float
    north: float
    crosses_antimeridian: bool


@dataclass(frozen=True)
class GeometryIssue:
    """Dato geométrico que se ha omitido sin impedir consultar el resto del viaje."""

    code: str
    message: str
    source_id: str | None = None


@dataclass(frozen=True)
class StopShapeDistance:
    stop_id: str | None
    distance_meters: float | None


@dataclass(frozen=True)
class MapStop:
    """Parada válida del viaje, preparada para su representación WGS84."""

    stop_id: str
    name: str | None
    coordinate: Coordinate
    stop_sequence: int | None = None


@dataclass(frozen=True)
class TripShapeGeometry:
    """Línea y métricas del shape asociado inequívocamente a un viaje."""

    trip_id: str
    shape_id: str | None
    coordinates: tuple[Coordinate, ...]
    length_meters: float | None
    bbox: BoundingBox | None
    stop_distances: tuple[StopShapeDistance, ...]
    distance_unit: str
    length_method: str
    distance_method: str
    issues: tuple[GeometryIssue, ...]
    stops: tuple[MapStop, ...] = ()
    route_color: str | None = None
    route_text_color: str | None = None
    route_id: str | None = None
