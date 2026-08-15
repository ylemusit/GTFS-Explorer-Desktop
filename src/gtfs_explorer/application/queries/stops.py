"""Casos de uso para inspeccionar eventos programados de una parada."""

from __future__ import annotations

from datetime import date

from gtfs_explorer.domain.ports import PageRequest, StopInspectorRepository
from gtfs_explorer.domain.stops import StopInspection


class StopInspectorQueries:
    """Expone contexto GTFS Schedule sin atribuirle datos de tiempo real."""

    def __init__(self, repository: StopInspectorRepository) -> None:
        self._repository = repository

    def inspect(
        self, stop_id: str, *, service_date: date | None = None, page: PageRequest
    ) -> StopInspection:
        """Devuelve eventos programados; ``service_date`` filtra servicios activos si existe."""
        return self._repository.inspect_stop(stop_id, service_date, page)
