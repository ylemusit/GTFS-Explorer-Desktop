"""Contrato de los puertos de persistencia contra DuckDB temporal."""

from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_explorer.domain.errors import RepositoryError
from gtfs_explorer.domain.ports import PageRequest, UnitOfWork
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )


def test_repositories_implement_ports_and_page_feed_inventory(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.executemany(
            "INSERT INTO stg_source_inventory "
            "(original_name, canonical_name, content_sha256, size_bytes, "
            "known_to_schedule_spec, loaded_row_count, staging_table_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("z.txt", "z.txt", "z", 3, False, None, None),
                ("a.txt", "a.txt", "a", 1, True, 2, "stg_a"),
                ("b.txt", "b.txt", "b", 2, True, 1, "stg_b"),
            ],
        )

    with DuckDbUnitOfWork(database) as unit_of_work:
        port: UnitOfWork = unit_of_work
        assert port.projects.schema_version() == 11
        result = port.feeds.source_files(PageRequest(offset=1, limit=1))

    assert result.total == 3
    assert [entry.original_name for entry in result.items] == ["b.txt"]
    assert result.items[0].loaded_row_count == 1
    assert result.next_offset == 2


def test_repository_errors_are_translated_to_domain_errors(tmp_path: Path) -> None:
    database = _database(tmp_path)
    database.initialize()
    with database.connection() as connection:
        connection.execute("DROP TABLE stg_source_inventory")

    with DuckDbUnitOfWork(database) as unit_of_work:
        with pytest.raises(RepositoryError, match="inventario del feed"):
            unit_of_work.feeds.source_files(PageRequest())


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 1), (0, 0), (0, 501)],
)
def test_page_request_rejects_unbounded_or_invalid_windows(offset: int, limit: int) -> None:
    with pytest.raises(ValueError):
        PageRequest(offset=offset, limit=limit)
