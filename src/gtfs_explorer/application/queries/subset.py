"""Caso de uso del cierre core Mini-GTFS."""

from __future__ import annotations

from gtfs_explorer.domain.ports import CoreSubsetRepository
from gtfs_explorer.domain.subset import CoreSubset, SubsetSelection, close_core_subset


class MiniGtfsSubsetQueries:
    """Construye un cierre core a partir de un puerto de lectura."""

    def __init__(self, repository: CoreSubsetRepository) -> None:
        self._repository = repository

    def close(self, selection: SubsetSelection) -> CoreSubset:
        return close_core_subset(self._repository.core_subset_source(), selection)
