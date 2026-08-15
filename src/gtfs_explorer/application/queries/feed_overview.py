"""Caso de uso del resumen de un feed GTFS Schedule."""

from __future__ import annotations

from gtfs_explorer.domain.overview import FeedOverview
from gtfs_explorer.domain.ports import FeedOverviewRepository


class FeedOverviewQueries:
    """Expone un resumen compacto sin filtrar SQL hacia la presentación."""

    def __init__(self, repository: FeedOverviewRepository) -> None:
        self._repository = repository

    def get(self) -> FeedOverview:
        return self._repository.overview()
