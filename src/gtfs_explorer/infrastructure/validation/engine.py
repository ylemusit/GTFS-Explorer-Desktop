"""Ejecución determinista y persistencia compacta de problemas de validación."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from gtfs_explorer.domain.errors import ImportCancelled
from gtfs_explorer.domain.validation import (
    CancellationCheck,
    LocalizedMessage,
    ValidationCategory,
    ValidationContext,
    ValidationIssue,
    ValidationRuleRegistry,
    ValidationSeverity,
    ValidationState,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection

_ENGINE_RULE_CODE = "VALIDATION_RULE_EXECUTION_FAILED"


@dataclass(frozen=True)
class ValidationRunResult:
    batch_id: str
    state: ValidationState
    total_issue_count: int
    stored_issue_count: int
    omitted_issue_count: int


class ValidationEngine:
    """Ejecuta reglas independientes sin permitir que una oculte las restantes."""

    def __init__(
        self, registry: ValidationRuleRegistry, *, max_distinct_issues: int = 10_000
    ) -> None:
        if max_distinct_issues < 1:
            raise ValueError("El límite de problemas distintos debe ser positivo.")
        self._registry = registry
        self._max_distinct_issues = max_distinct_issues

    def execute(
        self,
        connection: DatabaseConnection,
        *,
        feed_id: str,
        batch_id: str,
        is_cancelled: CancellationCheck | None = None,
    ) -> ValidationRunResult:
        if not feed_id or not batch_id:
            raise ValueError("feed_id y batch_id son obligatorios.")
        check_cancelled = is_cancelled or (lambda: False)
        context = ValidationContext(feed_id=feed_id, batch_id=batch_id)
        collector = _IssueCollector(self._max_distinct_issues)
        self._start_batch(connection, feed_id, batch_id)
        try:
            for rule in self._registry.ordered_rules():
                _raise_if_cancelled(check_cancelled)
                try:
                    for issue in rule.evaluate(context):
                        _raise_if_cancelled(check_cancelled)
                        collector.add(issue)
                except ImportCancelled:
                    raise
                except Exception:
                    collector.add(
                        ValidationIssue(
                            rule_code=_ENGINE_RULE_CODE,
                            severity=ValidationSeverity.FATAL,
                            category=ValidationCategory.ENGINE,
                            message=LocalizedMessage(
                                "validation.rule_execution_failed", {"rule_code": rule.code}
                            ),
                            entity=None,
                        )
                    )
            result = collector.result(batch_id)
            self._persist(connection, result, collector.issues())
            return result
        except ImportCancelled:
            self._finish_cancelled(connection, batch_id, collector.total_issue_count)
            raise

    @staticmethod
    def _start_batch(connection: DatabaseConnection, feed_id: str, batch_id: str) -> None:
        connection.execute(
            "INSERT INTO validation_runs (batch_id, feed_id, status, total_issue_count, "
            "stored_issue_count, omitted_issue_count) VALUES (?, ?, 'RUNNING', 0, 0, 0)",
            [batch_id, feed_id],
        )

    @staticmethod
    def _finish_cancelled(
        connection: DatabaseConnection, batch_id: str, total_issue_count: int
    ) -> None:
        connection.execute(
            "UPDATE validation_runs SET status = 'CANCELLED', total_issue_count = ? "
            "WHERE batch_id = ?",
            [total_issue_count, batch_id],
        )

    @staticmethod
    def _persist(
        connection: DatabaseConnection,
        result: ValidationRunResult,
        issues: Iterable[tuple[ValidationIssue, int]],
    ) -> None:
        for position, (issue, occurrence_count) in enumerate(issues, start=1):
            entity_type = issue.entity.entity_type if issue.entity else None
            entity_id = issue.entity.entity_id if issue.entity else None
            fingerprint = _fingerprint(issue)
            connection.execute(
                "INSERT INTO validation_issues (batch_id, position, fingerprint, validator, "
                "rule_code, "
                "severity, category, file_name, row_number, field_name, entity_type, entity_id, "
                "message_key, message_parameters, help_id, occurrence_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    result.batch_id,
                    position,
                    fingerprint,
                    issue.validator,
                    issue.rule_code,
                    issue.severity,
                    issue.category,
                    issue.file_name,
                    issue.row_number,
                    issue.field_name,
                    entity_type,
                    entity_id,
                    issue.message.key,
                    json.dumps(issue.message.parameters, sort_keys=True, separators=(",", ":")),
                    issue.help_id,
                    occurrence_count,
                ],
            )
        connection.execute(
            "UPDATE validation_runs SET status = ?, total_issue_count = ?, stored_issue_count = ?, "
            "omitted_issue_count = ? WHERE batch_id = ?",
            [
                result.state,
                result.total_issue_count,
                result.stored_issue_count,
                result.omitted_issue_count,
                result.batch_id,
            ],
        )


class _IssueCollector:
    def __init__(self, max_distinct_issues: int) -> None:
        self._max_distinct_issues = max_distinct_issues
        self._issues: dict[str, tuple[ValidationIssue, int]] = {}
        self.total_issue_count = 0
        self._omitted_issue_count = 0
        self._severities: set[ValidationSeverity] = set()

    def add(self, issue: ValidationIssue) -> None:
        self.total_issue_count += 1
        self._severities.add(issue.severity)
        fingerprint = _fingerprint(issue)
        current = self._issues.get(fingerprint)
        if current is not None:
            self._issues[fingerprint] = (current[0], current[1] + 1)
        elif len(self._issues) < self._max_distinct_issues:
            self._issues[fingerprint] = (issue, 1)
        else:
            self._omitted_issue_count += 1

    def issues(self) -> tuple[tuple[ValidationIssue, int], ...]:
        return tuple(self._issues[fingerprint] for fingerprint in sorted(self._issues))

    def result(self, batch_id: str) -> ValidationRunResult:
        if ValidationSeverity.FATAL in self._severities:
            state = ValidationState.IMPORT_FAILED
        elif ValidationSeverity.ERROR in self._severities:
            state = ValidationState.INVALID
        elif ValidationSeverity.WARNING in self._severities:
            state = ValidationState.VALID_WITH_WARNINGS
        else:
            state = ValidationState.VALID
        return ValidationRunResult(
            batch_id=batch_id,
            state=state,
            total_issue_count=self.total_issue_count,
            stored_issue_count=len(self._issues),
            omitted_issue_count=self._omitted_issue_count,
        )


def _raise_if_cancelled(check_cancelled: CancellationCheck) -> None:
    if check_cancelled():
        raise ImportCancelled("La validación se ha cancelado.")


def _fingerprint(issue: ValidationIssue) -> str:
    entity = issue.entity
    payload = {
        "category": issue.category,
        "entity_id": entity.entity_id if entity else None,
        "entity_type": entity.entity_type if entity else None,
        "field_name": issue.field_name,
        "file_name": issue.file_name,
        "message_key": issue.message.key,
        "message_parameters": dict(issue.message.parameters),
        "row_number": issue.row_number,
        "rule_code": issue.rule_code,
        "severity": issue.severity,
        "validator": issue.validator,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
