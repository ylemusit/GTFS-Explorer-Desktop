"""Caso de uso del inspector raw paginado de staging."""

from __future__ import annotations

from gtfs_explorer.domain.ports import RawInspectorRepository
from gtfs_explorer.domain.raw import RawPage, RawQuery


class RawInspectorQueries:
    """Expone filas fieles de staging mediante filtros estructurados y exportables."""

    def __init__(self, repository: RawInspectorRepository) -> None:
        self._repository = repository

    def query(self, request: RawQuery) -> RawPage:
        return self._repository.query(request)
