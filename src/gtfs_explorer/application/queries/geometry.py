"""Consulta de líneas y métricas para un viaje GTFS concreto."""

from __future__ import annotations

from gtfs_explorer.domain.geometry import TripShapeGeometry
from gtfs_explorer.domain.ports import GeometryRepository


class GeometryQueries:
    """Expone solo la geometría asociada de forma inequívoca a un viaje."""

    def __init__(self, repository: GeometryRepository) -> None:
        self._repository = repository

    def trip_shape(self, trip_id: str) -> TripShapeGeometry:
        return self._repository.trip_shape(trip_id)
