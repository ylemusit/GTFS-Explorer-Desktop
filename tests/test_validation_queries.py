"""Consulta paginada de incidencias para la vista de validación."""

from __future__ import annotations

from pathlib import Path

from gtfs_explorer.application.queries.validation import ValidationQueries
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.domain.validation import (
    ValidationCategory,
    ValidationIssueFilter,
    ValidationSeverity,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork


def test_validation_queries_filter_and_paginate_without_exposing_sql(tmp_path: Path) -> None:
    database = ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO projects VALUES ('project', 'Demo', 'READY', now(), now(), 8)"
        )
        connection.execute(
            "INSERT INTO feeds VALUES (?, ?, ?, ?, ?, ?, ?, now(), ?)",
            ["feed", "project", "demo.zip", "a" * 64, "STRICT", "2026-04-27", "0.1.0", "IMPORTED"],
        )
        connection.execute(
            "INSERT INTO validation_runs VALUES ('batch', 'feed', 'INVALID', 2, 2, 0)"
        )
        connection.executemany(
            "INSERT INTO validation_issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "batch",
                    1,
                    "one",
                    "internal",
                    "RULE_ERROR",
                    "ERROR",
                    "FIELD",
                    "stops.txt",
                    2,
                    "stop_id",
                    "stop",
                    "S1",
                    "validation.rule_error",
                    '{"value":"<script>"}',
                    "validation/RULE_ERROR",
                    1,
                ),
                (
                    "batch",
                    2,
                    "two",
                    "mobilitydata",
                    "RULE_NOTICE",
                    "NOTICE",
                    "BEST_PRACTICE",
                    None,
                    None,
                    None,
                    None,
                    None,
                    "validation.rule_notice",
                    "{}",
                    "validation/RULE_NOTICE",
                    3,
                ),
            ],
        )

    with DuckDbUnitOfWork(database) as unit_of_work:
        queries = ValidationQueries(unit_of_work.validation)
        page = queries.issues(
            ValidationIssueFilter(severities=frozenset({ValidationSeverity.ERROR})),
            PageRequest(limit=1),
        )

    assert page.total == 1
    assert page.items[0].rule_origin == "internal"
    assert page.items[0].message_parameters == {"value": "<script>"}
    assert page.items[0].entity is not None
    assert page.items[0].entity.entity_id == "S1"
    with DuckDbUnitOfWork(database) as unit_of_work:
        filtered = ValidationQueries(unit_of_work.validation).issues(
            ValidationIssueFilter(categories=frozenset({ValidationCategory.BEST_PRACTICE})),
            PageRequest(),
        )
    assert [issue.rule_code for issue in filtered.items] == ["RULE_NOTICE"]
