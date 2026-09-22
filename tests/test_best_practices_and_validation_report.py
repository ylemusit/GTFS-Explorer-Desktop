from __future__ import annotations

import json
from pathlib import Path

from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.domain.validation import (
    ValidationCategory,
    ValidationIssueFilter,
    ValidationRuleRegistry,
    ValidationSeverity,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories.base import DuckDbValidationRepository
from gtfs_explorer.infrastructure.exporting.validation_report import (
    ValidationReportExporter,
    ValidationReportFilter,
)
from gtfs_explorer.infrastructure.validation.best_practices import BestPracticeValidationRule
from gtfs_explorer.infrastructure.validation.engine import ValidationEngine


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


def _run_best_practices(database: ProjectDatabase, batch_id: str = "batch") -> None:
    with database.connection() as connection:
        registry = ValidationRuleRegistry()
        registry.register(BestPracticeValidationRule(connection))
        result = ValidationEngine(registry).execute(connection, feed_id="feed", batch_id=batch_id)
    assert result.state.value == "VALID"


def test_best_practices_are_not_validity_errors_and_are_traceable(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO gtfs_routes (source_filename, source_row, raw_values, route_id) "
            "VALUES ('routes.txt', 2, '{}', 'R-unused')"
        )
        connection.execute(
            "INSERT INTO gtfs_stops "
            "(source_filename, source_row, raw_values, stop_id, location_type) "
            "VALUES ('stops.txt', 4, '{}', 'S-unused', 0)"
        )
        connection.execute(
            "INSERT INTO gtfs_trips "
            "(source_filename, source_row, raw_values, route_id, service_id, trip_id) "
            "VALUES ('trips.txt', 5, '{}', 'R-unused', 'W', 'T-no-shape')"
        )

    _run_best_practices(database)

    with database.connection() as connection:
        rows = connection.execute(
            "SELECT rule_code, severity, category, message_parameters FROM validation_issues "
            "WHERE batch_id = 'batch' ORDER BY rule_code"
        ).fetchall()
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("GTFS_BP_STOP_WITHOUT_STOP_TIMES", "NOTICE", "BEST_PRACTICE"),
        ("GTFS_BP_TRIP_WITHOUT_SHAPE", "NOTICE", "BEST_PRACTICE"),
    ]
    assert all(json.loads(str(row[3]))["origin"] == "gtfs-explorer/best-practice" for row in rows)


def test_validation_report_filters_and_escapes_html(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.execute("INSERT INTO validation_runs VALUES ('batch', 'feed', 'VALID', 1, 1, 0)")
        connection.execute(
            "INSERT INTO validation_issues VALUES "
            "('batch', 1, 'fingerprint', 'gtfs-explorer', '<rule>', 'NOTICE', 'BEST_PRACTICE', "
            "'<script>.txt', 2, 'id', 'stop', '<img>', 'validation.<script>', "
            "'{\"value\":\"<script>alert(1)</script>\"}', 'validation/<rule>', 1)"
        )
        exporter = ValidationReportExporter()
        report_filter = ValidationReportFilter(
            severities=frozenset({ValidationSeverity.NOTICE}),
            categories=frozenset({ValidationCategory.BEST_PRACTICE}),
        )
        payload = exporter.build_payload(connection, batch_id="batch", report_filter=report_filter)
        exporter.write(
            connection,
            tmp_path / "validation.html",
            batch_id="batch",
            report_format="html",
            report_filter=report_filter,
        )
        exporter.write(
            connection,
            tmp_path / "validation.json",
            batch_id="batch",
            report_format="json",
        )

    assert payload["schema_version"] == "1.1.0"
    assert payload["selection"]["severity_occurrence_counts"] == {
        "FATAL": 0,
        "ERROR": 0,
        "WARNING": 0,
        "NOTICE": 1,
    }
    assert payload["issues"] == [
        {
            "rule": {"code": "<rule>", "origin": "gtfs-explorer"},
            "severity": "NOTICE",
            "category": "BEST_PRACTICE",
            "location": {
                "file": "<script>.txt",
                "row": 2,
                "field": "id",
                "entity_type": "stop",
                "entity_id": "<img>",
            },
            "message": {
                "key": "validation.<script>",
                "parameters": {"value": "<script>alert(1)</script>"},
            },
            "help_id": "validation/<rule>",
            "occurrence_count": 1,
        }
    ]
    html_contents = (tmp_path / "validation.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html_contents
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_contents
    assert "EXPORT / SELECTION INTEGRITY" in html_contents
    assert "Complete for selection" in html_contents
    assert "&lt;script&gt;.txt" in html_contents
    json_contents = json.loads((tmp_path / "validation.json").read_text(encoding="utf-8"))
    assert json_contents["report_type"] == "gtfs-explorer.validation"
    assert (tmp_path / "validation.html.manifest.json").exists()


def test_filtered_report_keeps_global_run_outcome_and_severity_counts(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO validation_runs VALUES ('batch', 'feed', 'INVALID', 3, 3, 0)"
        )
        connection.execute(
            "INSERT INTO validation_run_metadata VALUES "
            "('batch', 'COMPLETED', 'INVALID', 3, 3, TRUE, FALSE, now(), now())"
        )
        for position, severity in enumerate(("ERROR", "WARNING", "NOTICE"), 1):
            connection.execute(
                "INSERT INTO validation_issues VALUES (?, ?, ?, 'gtfs-explorer', ?, ?, "
                "'FIELD', 'stops.txt', 2, 'stop_id', 'stop', ?, 'validation.test', '{}', "
                "'validation/test', 1)",
                [
                    "batch",
                    position,
                    f"fingerprint-{severity}",
                    f"RULE_{severity}",
                    severity,
                    severity,
                ],
            )
            connection.execute(
                "INSERT INTO validation_severity_aggregates VALUES ('batch', ?, 1)", [severity]
            )
        report_filter = ValidationReportFilter(severities=frozenset({ValidationSeverity.NOTICE}))
        destination = tmp_path / "notice.json"
        manifest = ValidationReportExporter().write(
            connection,
            destination,
            batch_id="batch",
            report_format="json",
            report_filter=report_filter,
        )
        html_destination = tmp_path / "notice.html"
        ValidationReportExporter().write(
            connection,
            html_destination,
            batch_id="batch",
            report_format="html",
            report_filter=report_filter,
        )

    report = json.loads(destination.read_text(encoding="utf-8"))
    manifest_payload = json.loads(
        destination.with_name(manifest.manifest_name).read_text(encoding="utf-8")
    )
    assert report["run"] == {
        "id": "batch",
        "feed_id": "feed",
        "execution_status": "COMPLETED",
        "validation_outcome": "INVALID",
        "global_total_issue_count": 3,
        "integrity": {
            "detected_issue_count": 3,
            "persisted_issue_count": 3,
            "detail_complete": True,
            "legacy_truncated": False,
            "omitted_occurrence_count": 0,
        },
        "global_severity_occurrence_counts": {"FATAL": 0, "ERROR": 1, "WARNING": 1, "NOTICE": 1},
    }
    assert report["selection"]["active_filters"]["severities"] == ["NOTICE"]
    assert report["selection"]["selected_detail_row_count"] == 1
    assert report["selection"]["selected_occurrence_count"] == 1
    assert report["export"] == {
        "mode": "FULL",
        "exported_detail_row_count": 1,
        "exported_occurrence_count": 1,
        "complete_for_selection": True,
    }
    assert [issue["severity"] for issue in report["issues"]] == ["NOTICE"]
    assert manifest_payload["metadata"]["run_integrity"]["detected_issue_count"] == 3
    html_contents = html_destination.read_text(encoding="utf-8")
    assert "EXPORT / SELECTION INTEGRITY" in html_contents
    assert "Active filters" in html_contents
    assert "Selected occurrences</dt><dd>1" in html_contents
    assert "Exported occurrences</dt><dd>1" in html_contents
    assert "Complete for selection</dt><dd>True" in html_contents
    assert "&quot;global_total_issue_count&quot;: 3" in html_contents


def test_report_and_query_share_search_membership_for_every_supported_field(tmp_path: Path) -> None:
    database = _database(tmp_path)
    values = [
        ("RULE_TOKEN", "message.other", "field_other", "file_other", "entity_other"),
        ("RULE_OTHER", "message.token", "field_other", "file_other", "entity_other"),
        ("RULE_OTHER", "message.other", "field_token", "file_other", "entity_other"),
        ("RULE_OTHER", "message.other", "field_other", "file_token", "entity_other"),
        ("RULE_OTHER", "message.other", "field_other", "file_other", "entity_token"),
    ]
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO validation_runs VALUES ('batch', 'feed', 'INVALID', 5, 5, 0)"
        )
        connection.execute(
            "INSERT INTO validation_run_metadata VALUES "
            "('batch', 'COMPLETED', 'INVALID', 5, 5, TRUE, FALSE, now(), now())"
        )
        for position, (rule, message, field, file_name, entity_id) in enumerate(values, 1):
            connection.execute(
                "INSERT INTO validation_issues VALUES (?, ?, ?, 'validator', ?, 'ERROR', "
                "'FIELD', ?, 2, ?, 'stop', ?, ?, '{}', 'help', 1)",
                [
                    "batch",
                    position,
                    f"fingerprint-{position}",
                    rule,
                    file_name,
                    field,
                    entity_id,
                    message,
                ],
            )
        repository = DuckDbValidationRepository(connection)
        exporter = ValidationReportExporter()
        for token in ("rule_token", "message.token", "field_token", "file_token", "entity_token"):
            report_filter = ValidationIssueFilter(batch_id="batch", search_text=token)
            query = repository.issues(report_filter, PageRequest(limit=20))
            payload = exporter.build_payload(
                connection, batch_id="batch", report_filter=report_filter
            )
            assert len(payload["issues"]) == query.total == 1

        combined = ValidationIssueFilter(
            batch_id="batch", search_text="token", file_name="file_token", entity_type="stop"
        )
        assert repository.issues(combined, PageRequest(limit=20)).total == 1
        assert (
            len(
                exporter.build_payload(connection, batch_id="batch", report_filter=combined)[
                    "issues"
                ]
            )
            == 1
        )


def test_report_distinguishes_truncated_run_from_complete_selection(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO validation_runs VALUES ('legacy', 'feed', 'INVALID', 5, 1, 4)"
        )
        connection.execute(
            "INSERT INTO validation_run_metadata VALUES "
            "('legacy', 'COMPLETED', 'INVALID', 5, 3, FALSE, TRUE, now(), now())"
        )
        connection.execute(
            "INSERT INTO validation_issues VALUES "
            "('legacy', 1, 'fingerprint', 'validator', 'RÜLE', 'ERROR', 'FIELD', "
            "'stops.txt', 2, 'stop_id', 'stop', 'S1', 'message.key', '{}', 'help', 3)"
        )
        connection.execute(
            "INSERT INTO validation_severity_aggregates VALUES ('legacy', 'ERROR', 3)"
        )
        destination = tmp_path / "legacy.html"
        ValidationReportExporter().write(
            connection, destination, batch_id="legacy", report_format="html"
        )
        payload = ValidationReportExporter().build_payload(connection, batch_id="legacy")

    assert payload["run"]["integrity"] == {
        "detected_issue_count": 5,
        "persisted_issue_count": 3,
        "detail_complete": False,
        "legacy_truncated": True,
        "omitted_occurrence_count": 2,
    }
    assert payload["selection"]["selected_detail_row_count"] == 1
    assert payload["selection"]["selected_occurrence_count"] == 3
    contents = destination.read_text(encoding="utf-8")
    assert "no conserva todos los detalles detectados originalmente" in contents
    assert "legacy" in contents and "feed" in contents and "RÜLE" in contents
    assert "detail_complete" in contents and "false" in contents
    assert "legacy_truncated" in contents and "true" in contents
    assert "Complete for selection</dt><dd>True" in contents
    assert "Selected occurrences</dt><dd>3" in contents
    assert "Exported occurrences</dt><dd>3" in contents
