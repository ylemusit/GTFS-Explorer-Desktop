from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

from gtfs_explorer.domain.errors import ImportCancelled
from gtfs_explorer.domain.validation import (
    DuplicateRuleCodeError,
    LocalizedMessage,
    ValidationCategory,
    ValidationContext,
    ValidationIssue,
    ValidationRuleRegistry,
    ValidationSeverity,
    ValidationState,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.validation.engine import ValidationEngine


@dataclass
class _Rule:
    code: str
    issues: tuple[ValidationIssue, ...] = ()
    fails: bool = False
    severity: ValidationSeverity = ValidationSeverity.ERROR
    category: ValidationCategory = ValidationCategory.SCHEMA

    def evaluate(self, _context: ValidationContext) -> Iterable[ValidationIssue]:
        if self.fails:
            raise RuntimeError("fallo de prueba")
        return self.issues


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )
    database.initialize()
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO projects VALUES ('project', 'Test', 'READY', now(), now(), 8)"
        )
        connection.execute(
            "INSERT INTO feeds VALUES ('feed', 'project', 'test', 'hash', 'STRICT', '2026-04-27', "
            "'0.1.0', now(), 'READY')"
        )
    return database


def _issue(code: str) -> ValidationIssue:
    return ValidationIssue(
        rule_code=code,
        severity=ValidationSeverity.ERROR,
        category=ValidationCategory.SCHEMA,
        message=LocalizedMessage("validation.test", {"code": code}),
        file_name="stops.txt",
        row_number=2,
    )


def test_registry_rejects_duplicate_rule_codes() -> None:
    registry = ValidationRuleRegistry()
    registry.register(_Rule("GTFS_DUPLICATE"))

    with pytest.raises(DuplicateRuleCodeError, match="GTFS_DUPLICATE"):
        registry.register(_Rule("GTFS_DUPLICATE"))


def test_engine_orders_rules_and_isolates_a_failed_rule(tmp_path: Path) -> None:
    registry = ValidationRuleRegistry()
    registry.register(_Rule("GTFS_Z", (_issue("GTFS_Z"),)))
    registry.register(_Rule("GTFS_BROKEN", fails=True))
    registry.register(_Rule("GTFS_A", (_issue("GTFS_A"), _issue("GTFS_A"))))

    with _database(tmp_path).connection() as connection:
        result = ValidationEngine(registry).execute(connection, feed_id="feed", batch_id="batch")
        rows = connection.execute(
            "SELECT rule_code, occurrence_count FROM validation_issues "
            "WHERE batch_id = 'batch' ORDER BY position"
        ).fetchall()

    assert result.state is ValidationState.IMPORT_FAILED
    assert result.total_issue_count == 4
    assert rows == [
        ("GTFS_A", 2),
        ("GTFS_Z", 1),
        ("VALIDATION_RULE_EXECUTION_FAILED", 1),
    ]


def test_engine_marks_batch_cancelled_before_running_more_rules(tmp_path: Path) -> None:
    registry = ValidationRuleRegistry()
    registry.register(_Rule("GTFS_A", (_issue("GTFS_A"),)))
    checks = 0

    def is_cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks == 2

    with _database(tmp_path).connection() as connection:
        with pytest.raises(ImportCancelled):
            ValidationEngine(registry).execute(
                connection, feed_id="feed", batch_id="cancelled", is_cancelled=is_cancelled
            )
        row = connection.execute(
            "SELECT status, total_issue_count FROM validation_runs WHERE batch_id = 'cancelled'"
        ).fetchone()

    assert row == ("CANCELLED", 0)
