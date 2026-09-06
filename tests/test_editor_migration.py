"""Pruebas focales de migración reversible del almacenamiento del editor."""

from pathlib import Path

import pytest

from gtfs_explorer.application.commands.create_project import CreateProject
from gtfs_explorer.application.editor_session import EditorSession
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.editor_migration import (
    EditorMigrationError,
    migrate_editor_database,
)
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.duckdb.repositories.editor import DuckDbEditorRepository


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(
        tmp_path / "data.duckdb",
        tmp_path / "temp",
        settings=DatabaseSettings(memory_limit="256MB"),
    )
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO gtfs_stops (source_filename, source_row, raw_values, stop_id, "
            "stop_name, stop_lat, stop_lon) VALUES ('stops.txt', 1, '{}', 'S1', "
            "'Centro', 40.0, -3.0)"
        )
    return database


def test_editor_migration_is_idempotent_and_preserves_original_gtfs(tmp_path: Path) -> None:
    database = _database(tmp_path)
    first = migrate_editor_database(database)
    assert first.migrated is True
    assert first.backup_path is not None and first.backup_path.is_file()

    with database.connection() as connection:
        original = connection.execute(
            "SELECT stop_id, stop_name, stop_lat, stop_lon FROM gtfs_stops"
        ).fetchall()
        assert original == [("S1", "Centro", 40.0, -3.0)]
        assert connection.execute("SELECT count(*) FROM editor_revisions").fetchone() == (0,)
        assert connection.execute("SELECT base_revision_id FROM editor_state").fetchone() == (
            "original",
        )
        assert connection.execute("SELECT working_revision_id FROM editor_state").fetchone() == (
            "original",
        )
        assert connection.execute("SELECT count(*) FROM editor_deltas").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM editor_revision_deltas").fetchone() == (0,)
        assert connection.execute("SELECT schema_version FROM editor_schema").fetchone() == (2,)
        revision_columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'editor_revisions'"
            ).fetchall()
        }
        assert "entities_json" not in revision_columns

    second = migrate_editor_database(database)
    assert second == first.__class__(False)


def test_opening_a_legacy_project_prepares_a_clean_editor_draft(tmp_path: Path) -> None:
    project_directory = tmp_path / "project"
    project_directory.mkdir()

    opened = CreateProject(project_directory, name="Proyecto legado").execute()
    opened.close()

    with ProjectDatabase(
        project_directory / "data.duckdb",
        project_directory / "temp",
        settings=DatabaseSettings(memory_limit="256MB"),
    ).connection() as connection:
        assert connection.execute("SELECT count(*) FROM editor_state").fetchone() == (1,)
        assert connection.execute("SELECT cursor FROM editor_state").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM editor_deltas").fetchone() == (0,)


def test_legacy_initial_snapshot_is_removed_without_reading_or_preserving_it(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.execute(
            "CREATE TABLE editor_state ("
            "state_id INTEGER PRIMARY KEY, changeset_id VARCHAR NOT NULL, "
            "base_revision_id VARCHAR NOT NULL, cursor INTEGER NOT NULL, "
            "commands_json JSON NOT NULL, working_revision_id VARCHAR NOT NULL)"
        )
        connection.execute(
            "INSERT INTO editor_state VALUES (1, 'changeset', 'working-0', 0, '[]', 'working-0')"
        )
        connection.execute(
            "CREATE TABLE editor_history ("
            "action VARCHAR NOT NULL, command_id VARCHAR NOT NULL, created_at VARCHAR NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE editor_revisions ("
            "revision_id VARCHAR PRIMARY KEY, parent_revision_id VARCHAR, "
            "changeset_id VARCHAR NOT NULL, created_at VARCHAR NOT NULL, "
            "impact_json JSON NOT NULL, entities_json JSON NOT NULL)"
        )
        connection.execute(
            "INSERT INTO editor_revisions VALUES ('working-0', NULL, 'initial', "
            "'2026-09-03T00:00:00+00:00', '[]', '[{\"table\":\"gtfs_stops\","
            '"id":"S1","payload":{"stop_id":"S1"}}]\')'
        )

    result = migrate_editor_database(database)
    assert result.migrated is True
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM editor_revisions").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM editor_revision_deltas").fetchone() == (0,)
        assert connection.execute(
            "SELECT base_revision_id, working_revision_id FROM editor_state"
        ).fetchone() == ("original", "original")
        columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'editor_revisions'"
            ).fetchall()
        }
        assert "entities_json" not in columns


def test_legacy_published_snapshot_becomes_entity_deltas(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.execute(
            "CREATE TABLE editor_state ("
            "state_id INTEGER PRIMARY KEY, changeset_id VARCHAR NOT NULL, "
            "base_revision_id VARCHAR NOT NULL, cursor INTEGER NOT NULL, "
            "commands_json JSON NOT NULL, working_revision_id VARCHAR NOT NULL)"
        )
        connection.execute(
            "INSERT INTO editor_state VALUES (1, 'changeset', 'revision-1', 0, '[]', 'revision-1')"
        )
        connection.execute(
            "CREATE TABLE editor_history ("
            "action VARCHAR NOT NULL, command_id VARCHAR NOT NULL, created_at VARCHAR NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE editor_revisions ("
            "revision_id VARCHAR PRIMARY KEY, parent_revision_id VARCHAR, "
            "changeset_id VARCHAR NOT NULL, created_at VARCHAR NOT NULL, "
            "impact_json JSON NOT NULL, entities_json JSON NOT NULL)"
        )
        connection.execute(
            "INSERT INTO editor_revisions VALUES ('revision-1', 'working-0', 'changeset', "
            "'2026-09-03T00:00:00+00:00', '[]', '[{\"table\":\"gtfs_stops\","
            '"id":"S1","payload":{"stop_id":"S1","stop_name":"Editado",'
            '"stop_lat":41.0}}]\')'
        )

    migrate_editor_database(database)

    with database.connection() as connection:
        assert connection.execute(
            "SELECT parent_revision_id, delta_count FROM editor_revisions"
        ).fetchone() == ("original", 1)
        assert connection.execute(
            "SELECT table_name, entity_id, deleted, json_extract_string(payload, '$.stop_name') "
            "FROM editor_revision_deltas"
        ).fetchall() == [("gtfs_stops", "S1", False, "Editado")]

    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        assert session.working_revision_id == "revision-1"
        assert session.working_copy.get(("gtfs_stops", "S1"))["stop_name"] == "Editado"


def test_editor_migration_restores_original_bytes_after_injected_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(tmp_path)
    original_bytes = database.database_path.read_bytes()

    def fail_create_or_recover(self: DuckDbEditorRepository) -> object:
        raise RuntimeError("fallo inyectado")

    monkeypatch.setattr(DuckDbEditorRepository, "create_or_recover", fail_create_or_recover)
    with pytest.raises(EditorMigrationError):
        migrate_editor_database(database)

    assert database.database_path.read_bytes() == original_bytes
    with database.connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name LIKE 'editor_%'"
        ).fetchone() == (0,)
