"""Consultas tipadas de incidencias para la vista de validación."""

from __future__ import annotations

from gtfs_explorer.domain.ports import PagedResult, PageRequest, ValidationRepository
from gtfs_explorer.domain.validation import ValidationIssueFilter, ValidationIssueSummary


class ValidationQueries:
    """Mantiene la presentación ajena a DuckDB y a SQL."""

    def __init__(self, repository: ValidationRepository) -> None:
        self._repository = repository

    def issues(
        self, report_filter: ValidationIssueFilter, page: PageRequest
    ) -> PagedResult[ValidationIssueSummary]:
        return self._repository.issues(report_filter, page)
