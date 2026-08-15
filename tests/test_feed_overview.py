"""Contratos de la consulta que alimenta el resumen de feed."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from gtfs_explorer.application.queries.feed_overview import FeedOverviewQueries
from gtfs_explorer.domain.project import FeedMetadata, FeedStatus
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )


def test_feed_overview_distinguishes_unloaded_files_from_empty_loaded_files(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO projects VALUES ('project', 'Demo', 'READY', now(), now(), 8)"
        )
        connection.execute(
            "INSERT INTO feeds VALUES (?, ?, ?, ?, ?, ?, ?, now(), ?)",
            [
                "feed",
                "project",
                "demo.zip",
                "a" * 64,
                "STRICT",
                "2026-04-27",
                "0.1.0",
                "IMPORTED",
            ],
        )
        connection.executemany(
            "INSERT INTO stg_source_inventory VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("agency.txt", "agency.txt", "a", 1, True, 0, "stg_agency"),
                ("unknown.txt", "unknown.txt", "b", 2, False, None, None),
            ],
        )
        connection.execute(
            "INSERT INTO gtfs_stops "
            "(source_filename, source_row, raw_values, stop_id) VALUES ('stops.txt', 1, '{}', 'S1')"
        )
        connection.execute(
            "INSERT INTO gtfs_calendar "
            "(source_filename, source_row, raw_values, service_id, monday, tuesday, wednesday, "
            "thursday, friday, saturday, sunday, start_date, end_date) "
            "VALUES ('calendar.txt', 1, '{}', 'weekday', 1, 1, 1, 1, 1, 0, 0, ?, ?)",
            [date(2026, 1, 1), date(2026, 12, 31)],
        )
        connection.executemany(
            "INSERT INTO validation_runs VALUES (?, 'feed', ?, ?, ?, ?)",
            [("batch-1", "VALID", 0, 0, 0), ("batch-2", "INVALID", 2, 2, 0)],
        )

    with DuckDbUnitOfWork(database) as unit_of_work:
        overview = FeedOverviewQueries(unit_of_work.overview).get()

    assert overview.feed == FeedMetadata(
        "feed", "project", "demo.zip", "a" * 64, "STRICT", "2026-04-27", FeedStatus.IMPORTED
    )
    assert {metric.label: metric.value for metric in overview.metrics} == {
        "Agencias": 0,
        "Paradas": 1,
        "Rutas": 0,
        "Viajes": 0,
        "Eventos de parada": 0,
    }
    assert overview.period is not None
    assert overview.period.start_date == date(2026, 1, 1)
    assert [(item.name, item.row_count) for item in overview.files] == [
        ("agency.txt", 0),
        ("unknown.txt", None),
    ]
    assert overview.validation.run_count == 2
    assert overview.validation.total_issue_count == 2
    assert overview.validation.statuses == ("INVALID", "VALID")
