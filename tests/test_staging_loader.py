"""Integración de staging DuckDB fiel y transaccional de T015."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gtfs_explorer.domain.errors import ImportCancelled, TabularReadError
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import FieldSpec, FileSpec, ScheduleSpec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.importing.directory_source import DirectorySource
from gtfs_explorer.infrastructure.importing.staging_loader import StagingLoader


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )


def _spec() -> ScheduleSpec:
    fields = {
        "stop_id": FieldSpec("required", "ID", "STOP_ID", "test", (), None, None),
        "stop_name": FieldSpec("required", "Text", "STOP_NAME", "test", (), None, None),
    }
    return ScheduleSpec(
        "test", {}, {"stops.txt": FileSpec("required", "STOPS", "test", None, fields)}, {}
    )


def _manifest(source: Path):
    return DirectorySource().inventory(InputSource(source, InputSourceKind.DIRECTORY))


@pytest.mark.integration
def test_staging_loads_known_files_in_batches_and_inventories_unknown_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "stops.txt").write_text(
        "stop_id,stop_name,provider_note\n001,North,kept as extra\n002,South,second note\n",
        encoding="utf-8",
    )
    (source / "vendor_extension.txt").write_text("value\nx\n", encoding="utf-8")
    database = _database(tmp_path)

    result = StagingLoader(batch_size=1).load(database, source, _manifest(source), _spec())

    assert result.row_counts == {"stops.txt": 2}
    assert result.unknown_files == ("vendor_extension.txt",)
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM stg_stops").fetchone() == (2,)
        row = connection.execute(
            "SELECT source_row, stop_id, stop_name, extra_columns "
            "FROM stg_stops ORDER BY source_row"
        ).fetchone()
        assert row[:3] == (2, "001", "North")
        assert json.loads(row[3]) == [{"column": "provider_note", "value": "kept as extra"}]
        assert connection.execute(
            "SELECT known_to_schedule_spec, loaded_row_count, staging_table_name "
            "FROM stg_source_inventory WHERE original_name = 'vendor_extension.txt'"
        ).fetchone() == (False, None, None)
        assert connection.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'stg_vendor_extension'"
        ).fetchone() == (0,)


@pytest.mark.integration
def test_staging_rolls_back_rows_when_a_later_batch_has_a_tabular_error(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    stops = source / "stops.txt"
    stops.write_text("stop_id,stop_name\n001,North\n", encoding="utf-8")
    database = _database(tmp_path)
    loader = StagingLoader(batch_size=1)
    loader.load(database, source, _manifest(source), _spec())
    stops.write_text('stop_id,stop_name\n002,South\n003,"unterminated\n', encoding="utf-8")

    with pytest.raises(TabularReadError):
        loader.load(database, source, _manifest(source), _spec())

    with database.connection() as connection:
        assert connection.execute("SELECT stop_id FROM stg_stops").fetchall() == [("001",)]
        assert connection.execute(
            "SELECT loaded_row_count FROM stg_source_inventory"
        ).fetchone() == (1,)


@pytest.mark.integration
def test_staging_cancellation_reverts_every_insert_of_the_current_load(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "stops.txt").write_text("stop_id,stop_name\n001,North\n002,South\n", encoding="utf-8")
    database = _database(tmp_path)
    checks = 0

    def is_cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks == 4

    with pytest.raises(ImportCancelled):
        StagingLoader(batch_size=1).load(
            database, source, _manifest(source), _spec(), is_cancelled=is_cancelled
        )

    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM stg_source_inventory").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'stg_stops'"
        ).fetchone() == (0,)
