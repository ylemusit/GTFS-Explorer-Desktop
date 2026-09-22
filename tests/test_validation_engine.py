from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import pytest

from gtfs_explorer.domain.errors import ImportCancelled
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.domain.validation import (
    DuplicateRuleCodeError,
    LocalizedMessage,
    ValidationCategory,
    ValidationContext,
    ValidationEntity,
    ValidationIssue,
    ValidationIssueFilter,
    ValidationRuleRegistry,
    ValidationSeverity,
    ValidationState,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories.base import DuckDbValidationRepository
from gtfs_explorer.infrastructure.exporting.validation_report import ValidationReportExporter
from gtfs_explorer.infrastructure.validation import engine as validation_engine
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


def test_streaming_report_exports_20k_issues_in_multiple_batches(tmp_path: Path) -> None:
    class ManyIssuesRule:
        code = "GTFS_SCALE"
        severity = ValidationSeverity.ERROR
        category = ValidationCategory.SCHEMA

        def evaluate(self, _context: ValidationContext) -> Iterable[ValidationIssue]:
            for index in range(20_000):
                yield ValidationIssue(
                    rule_code=self.code,
                    severity=self.severity,
                    category=self.category,
                    message=LocalizedMessage("validation.test", {"index": index}),
                    entity=ValidationEntity("stop", f"S{index}"),
                )

    database = _database(tmp_path)
    registry = ValidationRuleRegistry()
    registry.register(ManyIssuesRule())
    with database.connection() as connection:
        started = perf_counter()
        result = ValidationEngine(registry).execute(connection, feed_id="feed", batch_id="scale")
        elapsed = perf_counter() - started
        counts = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(occurrence_count), 0) FROM validation_issues "
            "WHERE batch_id = 'scale'"
        ).fetchone()
        metadata = connection.execute(
            "SELECT detected_issue_count, persisted_issue_count, detail_complete, "
            "legacy_truncated FROM validation_run_metadata WHERE batch_id = 'scale'"
        ).fetchone()
        aggregate = connection.execute(
            "SELECT occurrence_count, affected_entity_count FROM validation_rule_aggregates "
            "WHERE batch_id = 'scale' AND rule_code = 'GTFS_SCALE'"
        ).fetchone()
        page_beyond_10k = connection.execute(
            "SELECT position FROM validation_issues WHERE batch_id = 'scale' "
            "ORDER BY position LIMIT 100 OFFSET 10000"
        ).fetchall()
        assert connection.execute(
            "SELECT COUNT(*) FROM validation_issues WHERE batch_id = 'scale' AND severity = 'ERROR'"
        ).fetchone() == (20_000,)
        progress: list[tuple[int, int]] = []
        ValidationReportExporter().write(
            connection,
            tmp_path / "scale.json",
            batch_id="scale",
            report_format="json",
            on_progress=lambda processed, total: progress.append((processed, total)),
        )
        ValidationReportExporter().write(
            connection,
            tmp_path / "scale-summary.json",
            batch_id="scale",
            report_format="json",
            mode="summary",
        )
    assert result.total_issue_count == 20_000
    assert result.stored_issue_count == 20_000
    assert result.persisted_issue_count == 20_000
    assert result.detail_complete is True
    assert elapsed <= 15
    assert counts == (20_000, 20_000)
    assert metadata == (20_000, 20_000, True, False)
    assert aggregate == (20_000, 20_000)
    assert len(page_beyond_10k) == 100
    assert progress == [(index, 20_000) for index in range(500, 20_001, 500)]
    report = json.loads((tmp_path / "scale.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == "1.1.0"
    assert report["run"]["global_total_issue_count"] == 20_000
    assert report["export"] == {
        "mode": "FULL",
        "exported_detail_row_count": 20_000,
        "exported_occurrence_count": 20_000,
        "complete_for_selection": True,
    }
    assert len(report["issues"]) == 20_000
    summary = json.loads((tmp_path / "scale-summary.json").read_text(encoding="utf-8"))
    assert "issues" not in summary
    assert summary["export"] == {
        "mode": "SUMMARY",
        "exported_detail_row_count": 0,
        "exported_occurrence_count": 0,
        "complete_for_selection": False,
    }


def test_json_batch_transport_preserves_values_and_accumulates_across_buffers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issue = ValidationIssue(
        rule_code="GTFS_JSON",
        severity=ValidationSeverity.ERROR,
        category=ValidationCategory.SCHEMA,
        message=LocalizedMessage("validation.ñ", {"empty": None, "text": "áéíóú"}),
        entity=ValidationEntity("stop", "S1"),
    )
    other = ValidationIssue(
        rule_code="GTFS_JSON_OTHER",
        severity=ValidationSeverity.WARNING,
        category=ValidationCategory.SCHEMA,
        message=LocalizedMessage("validation.empty"),
        file_name=None,
        row_number=None,
        field_name=None,
    )
    monkeypatch.setattr(validation_engine, "_PERSIST_BATCH_SIZE", 2)
    registry = ValidationRuleRegistry()
    registry.register(_Rule("GTFS_JSON", (issue, issue, issue, other)))

    with _database(tmp_path).connection() as connection:
        ValidationEngine(registry).execute(connection, feed_id="feed", batch_id="json")
        rows = connection.execute(
            "SELECT rule_code, occurrence_count, message_key, message_parameters, file_name, "
            "row_number, field_name FROM validation_issues WHERE batch_id = 'json' "
            "ORDER BY rule_code"
        ).fetchall()

    assert rows == [
        ("GTFS_JSON", 3, "validation.ñ", '{"empty":null,"text":"áéíóú"}', None, None, None),
        ("GTFS_JSON_OTHER", 1, "validation.empty", "{}", None, None, None),
    ]


def test_persistence_failure_rolls_back_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def fail_flush(_collector: object) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("persistence failure")

    monkeypatch.setattr(validation_engine._StreamingIssueCollector, "flush", fail_flush)
    registry = ValidationRuleRegistry()
    registry.register(_Rule("GTFS_A", (_issue("GTFS_A"),)))

    with _database(tmp_path).connection() as connection:
        with pytest.raises(RuntimeError, match="persistence failure"):
            ValidationEngine(registry).execute(connection, feed_id="feed", batch_id="failed")
        assert connection.execute(
            "SELECT status, stored_issue_count, omitted_issue_count FROM validation_runs "
            "WHERE batch_id = 'failed'"
        ).fetchone() == ("IMPORT_FAILED", 0, 1)
        assert connection.execute(
            "SELECT COUNT(*) FROM validation_issues WHERE batch_id = 'failed'"
        ).fetchone() == (0,)

    assert calls == 1


def test_registry_rejects_duplicate_rule_codes() -> None:
    registry = ValidationRuleRegistry()
    registry.register(_Rule("GTFS_DUPLICATE"))

    with pytest.raises(DuplicateRuleCodeError, match="GTFS_DUPLICATE"):
        registry.register(_Rule("GTFS_DUPLICATE"))


def test_legacy_truncated_run_remains_truthful_and_new_runs_are_complete(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO validation_runs VALUES ('legacy', 'feed', 'INVALID', 72608, 10000, 62608)"
        )
        connection.execute(
            "INSERT INTO validation_run_metadata VALUES "
            "('legacy', 'COMPLETED', 'INVALID', 72608, 10000, FALSE, TRUE, now(), now())"
        )
        connection.execute(
            "INSERT INTO validation_issues VALUES "
            "('legacy', 1, 'legacy-fingerprint', 'gtfs-explorer', 'LEGACY_RULE', 'ERROR', "
            "'FIELD', 'stops.txt', 2, 'stop_id', 'stop', 'S1', 'validation.test', '{}', "
            "'validation/LEGACY_RULE', 1)"
        )
        repository = DuckDbValidationRepository(connection)
        legacy = repository.run_summary("legacy")
        details = repository.issues(ValidationIssueFilter(batch_id="legacy"), PageRequest())
        registry = ValidationRuleRegistry()
        registry.register(_Rule("GTFS_CURRENT", (_issue("GTFS_CURRENT"),)))
        current = ValidationEngine(registry).execute(connection, feed_id="feed", batch_id="current")

    assert legacy is not None
    assert legacy.detected_issue_count == 72608
    assert legacy.persisted_issue_count == 10000
    assert legacy.detail_complete is False
    assert legacy.legacy_truncated is True
    assert details.total == 1
    assert details.items[0].rule_code == "LEGACY_RULE"
    assert current.detail_complete is True
    assert current.persisted_issue_count == 1


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
