"""Integración de migraciones y conexiones DuckDB de T020."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from gtfs_explorer.infrastructure.duckdb.database import (
    ConnectionThreadError,
    DatabaseCorruptionError,
    DatabaseSettings,
    MigrationError,
    ProjectDatabase,
)


def _database(tmp_path: Path, *, migrations_directory: Path | None = None) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "proyecto.duckdb",
        tmp_path / "temporales",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
        migrations_directory=migrations_directory,
    )


def test_empty_database_migrates_and_context_manager_closes_connection(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with database.connection() as connection:
        assert connection.execute("SELECT schema_version FROM schema_metadata").fetchone() == (11,)
        assert connection.execute("SELECT current_setting('threads')").fetchone() == (1,)

    with pytest.raises(Exception):
        connection.execute("SELECT 1")


def test_previous_schema_migrates_and_is_backed_up(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_schema_control.sql").write_text(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP NOT NULL);
        CREATE TABLE schema_metadata (schema_version INTEGER NOT NULL CHECK (schema_version >= 0));
        INSERT INTO schema_metadata (schema_version) VALUES (0);
        """,
        encoding="utf-8",
    )
    previous = _database(tmp_path, migrations_directory=migrations)
    assert previous.initialize() == 1
    database_path = previous.database_path
    before = database_path.read_bytes()

    current = _database(tmp_path)
    assert current.initialize() == 11
    assert current.backup_path.read_bytes() == before
    with current.connection() as connection:
        assert connection.execute("SELECT schema_version FROM schema_metadata").fetchone() == (11,)


def test_schema_8_migrates_through_9_and_10_without_backfill_and_keeps_backup(
    tmp_path: Path,
) -> None:
    migrations = tmp_path / "schema-8"
    migrations.mkdir()
    source_directory = (
        Path(__file__)
        .parents[1]
        .joinpath("src", "gtfs_explorer", "infrastructure", "duckdb", "migrations")
    )
    for source in source_directory.glob("00[1-8]_*.sql"):
        (migrations / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    schema_8 = _database(tmp_path, migrations_directory=migrations)
    assert schema_8.initialize() == 8
    before = schema_8.database_path.read_bytes()

    migration_9 = source_directory / "009_operations_history.sql"
    (migrations / migration_9.name).write_text(
        migration_9.read_text(encoding="utf-8"), encoding="utf-8"
    )
    schema_9 = _database(tmp_path, migrations_directory=migrations)
    assert schema_9.initialize() == 9
    assert schema_9.backup_path.read_bytes() == before

    current = _database(tmp_path)
    assert current.initialize() == 11
    with current.connection() as connection:
        assert connection.execute("SELECT schema_version FROM schema_metadata").fetchone() == (11,)
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert versions == [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,), (10,), (11,)]
        assert connection.execute("SELECT count(*) FROM operations").fetchone() == (0,)


def test_failed_schema_9_migration_rolls_back_to_schema_8(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    source_directory = (
        Path(__file__)
        .parents[1]
        .joinpath("src", "gtfs_explorer", "infrastructure", "duckdb", "migrations")
    )
    for source in source_directory.glob("00[1-8]_*.sql"):
        (migrations / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    database = _database(tmp_path, migrations_directory=migrations)
    assert database.initialize() == 8
    before = database.database_path.read_bytes()
    (migrations / "009_operations_history.sql").write_text("BROKEN SQL;", encoding="utf-8")

    with pytest.raises(MigrationError):
        database.initialize()

    assert database.backup_path.read_bytes() == before
    (migrations / "009_operations_history.sql").unlink()
    with database.connection() as connection:
        assert connection.execute("SELECT schema_version FROM schema_metadata").fetchone() == (8,)


def test_failed_migration_is_rolled_back_and_preserves_backup(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for source in (
        Path(__file__)
        .parents[1]
        .joinpath("src", "gtfs_explorer", "infrastructure", "duckdb", "migrations")
        .glob("00[12]_*.sql")
    ):
        (migrations / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    initial = _database(tmp_path, migrations_directory=migrations)
    assert initial.initialize() == 2
    before = initial.database_path.read_bytes()
    (migrations / "003_broken.sql").write_text(
        "CREATE TABLE migration_should_rollback (id INTEGER); BROKEN SQL;", encoding="utf-8"
    )

    with pytest.raises(MigrationError):
        initial.initialize()

    assert initial.backup_path.read_bytes() == before
    (migrations / "003_broken.sql").unlink()
    with initial.connection() as connection:
        assert connection.execute("SELECT schema_version FROM schema_metadata").fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'migration_should_rollback'"
        ).fetchone() == (0,)


def test_connection_rejects_use_from_another_thread(tmp_path: Path) -> None:
    database = _database(tmp_path)
    connection = database.connect()
    errors: list[BaseException] = []

    def use_connection() -> None:
        try:
            connection.execute("SELECT 1")
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=use_connection)
    worker.start()
    worker.join()
    connection.close()

    assert len(errors) == 1
    assert isinstance(errors[0], ConnectionThreadError)


def test_corrupt_database_is_reported_without_overwriting_source(tmp_path: Path) -> None:
    database = _database(tmp_path)
    database.database_path.write_bytes(b"no es una base DuckDB")

    with pytest.raises(DatabaseCorruptionError):
        database.initialize()

    assert database.database_path.read_bytes() == b"no es una base DuckDB"
