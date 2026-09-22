"""Consultas tipadas de incidencias para la vista de validación."""

from __future__ import annotations

from gtfs_explorer.domain.ports import PagedResult, PageRequest, ValidationRepository
from gtfs_explorer.domain.validation import (
    ValidationIssueFilter,
    ValidationIssueSummary,
    ValidationRuleSummary,
    ValidationRunSummary,
)


class ValidationQueries:
    """Mantiene la presentación ajena a DuckDB y a SQL."""

    def __init__(self, repository: ValidationRepository) -> None:
        self._repository = repository

    def issues(
        self, report_filter: ValidationIssueFilter, page: PageRequest
    ) -> PagedResult[ValidationIssueSummary]:
        return self._repository.issues(report_filter, page)

    def files(self, *, feed_id: str | None = None) -> tuple[str, ...]:
        """Devuelve solo nombres de archivo presentes en el contexto consultado."""
        return self._repository.files(ValidationIssueFilter(feed_id=feed_id))

    def run_summary(self, batch_id: str) -> ValidationRunSummary | None:
        return self._repository.run_summary(batch_id)

    def rule_summaries(
        self, report_filter: ValidationIssueFilter
    ) -> tuple[ValidationRuleSummary, ...]:
        return self._repository.rule_summaries(report_filter)
