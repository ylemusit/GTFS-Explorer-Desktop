"""Inspector raw paginado: contrato seguro sobre staging DuckDB."""

from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_explorer.application.queries.raw import RawInspectorQueries
from gtfs_explorer.domain.raw import RawFilter, RawQuery, RawSort
from gtfs_explorer.domain.spec import FieldSpec, FileSpec, ScheduleSpec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories.base import DuckDbRawInspectorRepository


def _spec() -> ScheduleSpec:
    def field(value_type: str) -> FieldSpec:
        return FieldSpec("optional", value_type, "rule", "source", (), None, None)

    return ScheduleSpec(
        "2026-04-27",
        {"url": "https://example.invalid", "revised": "2026-04-27", "sha256": "a" * 64},
        {
            "stops.txt": FileSpec(
                "required",
                "file-rule",
                "source",
                None,
                {"stop_name": field("Text"), "stop_lat": field("Latitude"), "date": field("Date")},
            )
        },
        {},
    )


def _repository(tmp_path: Path) -> DuckDbRawInspectorRepository:
    database = ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )
    connection = database.connect()
    connection.execute(
        'CREATE TABLE "stg_stops" '
        "(source_row BIGINT, stop_name VARCHAR, stop_lat VARCHAR, date VARCHAR)"
    )
    connection.executemany(
        'INSERT INTO "stg_stops" VALUES (?, ?, ?, ?)',
        [
            (1, "Parada Ñandú", "43.5", "20260102"),
            (2, "Estación Águila", "42.1", "20260101"),
            *[(index, f"Stop {index}", str(index), "20260103") for index in range(3, 1004)],
        ],
    )
    return DuckDbRawInspectorRepository(connection, _spec())


@pytest.mark.integration
def test_raw_inspector_uses_structured_filters_unicode_ranges_and_page_tokens(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    queries = RawInspectorQueries(repository)

    first = queries.query(
        RawQuery(
            "stops.txt",
            ("stop_name", "stop_lat"),
            filters=(RawFilter("stop_name", "contains", "Ñ"),),
            sort=(RawSort("stop_lat", "desc"),),
            page_size=1,
        )
    )

    assert first.rows[0].values == ("Parada Ñandú", "43.5")
    assert first.next_page_token is None

    ranged = queries.query(
        RawQuery(
            "stops.txt",
            ("stop_name", "date"),
            filters=(RawFilter("date", "gte", "20260102"),),
            page_size=2,
        )
    )
    assert len(ranged.rows) == 2
    assert ranged.next_page_token is not None
    second = queries.query(
        RawQuery(
            "stops.txt",
            ("stop_name", "date"),
            page_size=2,
            page_token=ranged.next_page_token,
            filters=(RawFilter("date", "gte", "20260102"),),
        )
    )
    assert second.rows[0].source_row == 4


@pytest.mark.integration
def test_raw_inspector_rejects_sql_in_columns_and_filters_and_invalid_tokens(
    tmp_path: Path,
) -> None:
    queries = RawInspectorQueries(_repository(tmp_path))

    with pytest.raises(ValueError, match="manifiesto"):
        queries.query(RawQuery("stops.txt", ('stop_name"; DROP TABLE stg_stops; --',)))
    with pytest.raises(ValueError, match="manifiesto"):
        queries.query(
            RawQuery(
                "stops.txt",
                ("stop_name",),
                filters=(RawFilter('stop_name" OR 1=1 --', "equals", "x"),),
            )
        )
    with pytest.raises(ValueError, match="token"):
        queries.query(RawQuery("stops.txt", ("stop_name",), page_token="not-a-token"))


@pytest.mark.integration
def test_raw_inspector_bounds_large_table_response(tmp_path: Path) -> None:
    queries = RawInspectorQueries(_repository(tmp_path))

    page = queries.query(RawQuery("stops.txt", ("stop_name",), page_size=500))

    assert len(page.rows) == 500
    assert page.next_page_token is not None
