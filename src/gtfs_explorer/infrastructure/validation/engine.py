"""Ejecución de validaciones con persistencia incremental y trazable."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from gtfs_explorer.domain.errors import ImportCancelled
from gtfs_explorer.domain.validation import (
    CancellationCheck,
    LocalizedMessage,
    ValidationCategory,
    ValidationContext,
    ValidationExecutionStatus,
    ValidationIssue,
    ValidationOutcome,
    ValidationRuleRegistry,
    ValidationSeverity,
    ValidationState,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection

_ENGINE_RULE_CODE = "VALIDATION_RULE_EXECUTION_FAILED"
_PERSIST_BATCH_SIZE = 1_000
_ISSUE_BATCH_JSON_SCHEMA = (
    '[{"batch_id":"VARCHAR","position":"BIGINT","fingerprint":"VARCHAR",'
    '"validator":"VARCHAR","rule_code":"VARCHAR","severity":"VARCHAR",'
    '"category":"VARCHAR","file_name":"VARCHAR","row_number":"BIGINT",'
    '"field_name":"VARCHAR","entity_type":"VARCHAR","entity_id":"VARCHAR",'
    '"message_key":"VARCHAR","message_parameters":"JSON","help_id":"VARCHAR",'
    '"occurrence_count":"BIGINT"}]'
)


def _database_integer(value: object) -> int:
    if not isinstance(value, int):
        raise ValueError("La base de datos devolvió un contador no entero.")
    return value


@dataclass(frozen=True)
class ValidationRunResult:
    batch_id: str
    state: ValidationState
    execution_status: ValidationExecutionStatus
    outcome: ValidationOutcome | None
    total_issue_count: int
    stored_issue_count: int
    omitted_issue_count: int
    persisted_issue_count: int
    detail_complete: bool


class ValidationEngine:
    """Ejecuta reglas sin límite arbitrario y persiste detalles por lotes."""

    def __init__(self, registry: ValidationRuleRegistry) -> None:
        self._registry = registry

    def execute(
        self,
        connection: DatabaseConnection,
        *,
        feed_id: str,
        batch_id: str,
        is_cancelled: CancellationCheck | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> ValidationRunResult:
        if not feed_id or not batch_id:
            raise ValueError("feed_id y batch_id son obligatorios.")
        check_cancelled = is_cancelled or (lambda: False)
        connection.execute("BEGIN TRANSACTION")
        collector = _StreamingIssueCollector(connection, batch_id)
        context = ValidationContext(feed_id=feed_id, batch_id=batch_id)
        try:
            self._start_batch(connection, feed_id, batch_id)
            for rule in self._registry.ordered_rules():
                _raise_if_cancelled(check_cancelled)
                if on_progress:
                    on_progress(rule.code)
                try:
                    for issue in rule.evaluate(context):
                        _raise_if_cancelled(check_cancelled)
                        collector.add(issue)
                except ImportCancelled:
                    raise
                except Exception:
                    collector.add(_engine_failure_issue(rule.code))
            collector.flush()
            self._persist(connection, collector)
            collector.refresh_stored_count()
            result = self._finish_batch(connection, batch_id, collector, collector.outcome())
            connection.execute("COMMIT")
            return result
        except ImportCancelled:
            connection.execute("ROLLBACK")
            self._finish_cancelled(connection, feed_id, batch_id, collector)
            raise
        except Exception:
            connection.execute("ROLLBACK")
            self._finish_failed(connection, feed_id, batch_id, collector)
            raise

    @staticmethod
    def _start_batch(connection: DatabaseConnection, feed_id: str, batch_id: str) -> None:
        connection.execute(
            "INSERT INTO validation_runs (batch_id, feed_id, status, total_issue_count, "
            "stored_issue_count, omitted_issue_count) VALUES (?, ?, 'RUNNING', 0, 0, 0)",
            [batch_id, feed_id],
        )
        connection.execute(
            "INSERT INTO validation_run_metadata "
            "(batch_id, execution_status, detected_issue_count, "
            "persisted_issue_count, detail_complete, legacy_truncated) "
            "VALUES (?, 'RUNNING', 0, 0, TRUE, FALSE)",
            [batch_id],
        )

    @staticmethod
    def _persist(connection: DatabaseConnection, _collector: _StreamingIssueCollector) -> None:
        """Punto de extensión conservado para detectar fallos de persistencia."""

    @staticmethod
    def _finish_batch(
        connection: DatabaseConnection,
        batch_id: str,
        collector: _StreamingIssueCollector,
        outcome: ValidationOutcome,
    ) -> ValidationRunResult:
        _refresh_aggregates(connection, batch_id)
        state = (
            ValidationState.IMPORT_FAILED if collector.has_fatal else _state_for_outcome(outcome)
        )
        connection.execute(
            "UPDATE validation_runs SET status = ?, total_issue_count = ?, stored_issue_count = ?, "
            "omitted_issue_count = 0 WHERE batch_id = ?",
            [state, collector.total_issue_count, collector.stored_issue_count, batch_id],
        )
        connection.execute(
            "UPDATE validation_run_metadata SET execution_status = 'COMPLETED', "
            "validation_outcome = ?, "
            "detected_issue_count = ?, persisted_issue_count = ?, detail_complete = TRUE, "
            "finished_at = CURRENT_TIMESTAMP WHERE batch_id = ?",
            [outcome, collector.total_issue_count, collector.total_issue_count, batch_id],
        )
        return ValidationRunResult(
            batch_id,
            state,
            ValidationExecutionStatus.COMPLETED,
            outcome,
            collector.total_issue_count,
            collector.stored_issue_count,
            0,
            collector.total_issue_count,
            True,
        )

    @staticmethod
    def _finish_cancelled(
        connection: DatabaseConnection,
        feed_id: str,
        batch_id: str,
        collector: _StreamingIssueCollector,
    ) -> None:
        _finish_incomplete(connection, feed_id, batch_id, collector, "CANCELLED")

    @staticmethod
    def _finish_failed(
        connection: DatabaseConnection,
        feed_id: str,
        batch_id: str,
        collector: _StreamingIssueCollector,
    ) -> None:
        _finish_incomplete(connection, feed_id, batch_id, collector, "IMPORT_FAILED")


def _finish_incomplete(
    connection: DatabaseConnection,
    feed_id: str,
    batch_id: str,
    collector: _StreamingIssueCollector,
    status: str,
) -> None:
    """Registra el terminal después del rollback, sin detalles persistidos."""
    connection.execute("BEGIN TRANSACTION")
    connection.execute(
        "INSERT INTO validation_runs (batch_id, feed_id, status, total_issue_count, "
        "stored_issue_count, omitted_issue_count) VALUES (?, ?, ?, ?, 0, ?)",
        [batch_id, feed_id, status, collector.total_issue_count, collector.total_issue_count],
    )
    execution_status = "CANCELLED" if status == "CANCELLED" else "FAILED"
    connection.execute(
        "INSERT INTO validation_run_metadata (batch_id, execution_status, validation_outcome, "
        "detected_issue_count, persisted_issue_count, detail_complete, legacy_truncated, "
        "finished_at) VALUES (?, ?, NULL, ?, 0, FALSE, FALSE, CURRENT_TIMESTAMP)",
        [batch_id, execution_status, collector.total_issue_count],
    )
    connection.execute("COMMIT")


class _StreamingIssueCollector:
    def __init__(self, connection: DatabaseConnection, batch_id: str) -> None:
        self._connection, self._batch_id = connection, batch_id
        self._pending: list[ValidationIssue] = []
        self._severities: set[ValidationSeverity] = set()
        self.total_issue_count = 0
        self.stored_issue_count = 0

    def add(self, issue: ValidationIssue) -> None:
        self.total_issue_count += 1
        self._severities.add(issue.severity)
        self._pending.append(issue)
        if len(self._pending) >= _PERSIST_BATCH_SIZE:
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            return
        rows_by_fingerprint: dict[str, dict[str, object]] = {}
        for issue in self._pending:
            entity_type = issue.entity.entity_type if issue.entity else None
            entity_id = issue.entity.entity_id if issue.entity else None
            fingerprint = _fingerprint(issue)
            row = rows_by_fingerprint.get(fingerprint)
            if row is not None:
                row["occurrence_count"] = _database_integer(row["occurrence_count"]) + 1
                continue
            rows_by_fingerprint[fingerprint] = {
                "batch_id": self._batch_id,
                "position": int(fingerprint[:15], 16),
                "fingerprint": fingerprint,
                "validator": issue.validator,
                "rule_code": issue.rule_code,
                "severity": issue.severity,
                "category": issue.category,
                "file_name": issue.file_name,
                "row_number": issue.row_number,
                "field_name": issue.field_name,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "message_key": issue.message.key,
                "message_parameters": dict(issue.message.parameters),
                "help_id": issue.help_id,
                "occurrence_count": 1,
            }
        payload = json.dumps(
            tuple(rows_by_fingerprint.values()),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self._connection.execute(
            "INSERT INTO validation_issues (batch_id, position, fingerprint, validator, rule_code, "
            "severity, category, file_name, row_number, field_name, entity_type, entity_id, "
            "message_key, message_parameters, help_id, occurrence_count) "
            "SELECT row.batch_id, row.position, row.fingerprint, row.validator, row.rule_code, "
            "row.severity, row.category, row.file_name, row.row_number, row.field_name, "
            "row.entity_type, row.entity_id, row.message_key, row.message_parameters, row.help_id, "
            "row.occurrence_count "
            f"FROM UNNEST(from_json(?::JSON, '{_ISSUE_BATCH_JSON_SCHEMA}')) AS rows(row) "
            "ON CONFLICT (batch_id, fingerprint) DO UPDATE SET "
            "occurrence_count = validation_issues.occurrence_count + excluded.occurrence_count",
            [payload],
        )
        self._pending.clear()

    def refresh_stored_count(self) -> None:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM validation_issues WHERE batch_id = ?", [self._batch_id]
        ).fetchone()
        if row is None:
            raise ValueError("La consulta de incidencias no devolvió un contador.")
        self.stored_issue_count = _database_integer(row[0])

    def outcome(self) -> ValidationOutcome:
        if (
            ValidationSeverity.FATAL in self._severities
            or ValidationSeverity.ERROR in self._severities
        ):
            return ValidationOutcome.INVALID
        if ValidationSeverity.WARNING in self._severities:
            return ValidationOutcome.VALID_WITH_WARNINGS
        if ValidationSeverity.NOTICE in self._severities:
            return ValidationOutcome.VALID_WITH_NOTICES
        return ValidationOutcome.VALID

    @property
    def has_fatal(self) -> bool:
        return ValidationSeverity.FATAL in self._severities


def _refresh_aggregates(connection: DatabaseConnection, batch_id: str) -> None:
    connection.execute("DELETE FROM validation_severity_aggregates WHERE batch_id = ?", [batch_id])
    connection.execute("DELETE FROM validation_rule_aggregates WHERE batch_id = ?", [batch_id])
    connection.execute(
        "INSERT INTO validation_severity_aggregates "
        "SELECT batch_id, severity, SUM(occurrence_count) FROM validation_issues "
        "WHERE batch_id = ? GROUP BY batch_id, severity",
        [batch_id],
    )
    connection.execute(
        "INSERT INTO validation_rule_aggregates "
        "SELECT batch_id, validator, rule_code, severity, category, "
        "SUM(occurrence_count), COUNT(DISTINCT CASE WHEN entity_type IS NULL OR entity_id IS NULL "
        "THEN NULL ELSE entity_type || chr(31) || entity_id END) "
        "FROM validation_issues WHERE batch_id = ? "
        "GROUP BY batch_id, rule_code, validator, severity, category",
        [batch_id],
    )


def _engine_failure_issue(rule_code: str) -> ValidationIssue:
    return ValidationIssue(
        rule_code=_ENGINE_RULE_CODE,
        severity=ValidationSeverity.FATAL,
        category=ValidationCategory.ENGINE,
        message=LocalizedMessage("validation.rule_execution_failed", {"rule_code": rule_code}),
        entity=None,
    )


def _state_for_outcome(outcome: ValidationOutcome) -> ValidationState:
    if outcome is ValidationOutcome.INVALID:
        return ValidationState.INVALID
    if outcome is ValidationOutcome.VALID_WITH_WARNINGS:
        return ValidationState.VALID_WITH_WARNINGS
    return ValidationState.VALID


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
