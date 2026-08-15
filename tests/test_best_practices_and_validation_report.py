from __future__ import annotations

import json
from pathlib import Path

from gtfs_explorer.domain.validation import (
    ValidationCategory,
    ValidationRuleRegistry,
    ValidationSeverity,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
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

    assert payload["schema_version"] == "1.0.0"
    assert payload["summary_by_severity"] == {
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
    json_contents = json.loads((tmp_path / "validation.json").read_text(encoding="utf-8"))
    assert json_contents["report_type"] == "gtfs-explorer.validation"
    assert (tmp_path / "validation.html.manifest.json").exists()
