"""Regresiones del ciclo real de apertura sobre migraciones DuckDB."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import duckdb
import pytest

import gtfs_explorer.application.commands.open_project as open_project_module
from gtfs_explorer.application.commands.open_project import OpenProject, ProjectWriterLock
from gtfs_explorer.domain.project import FeedMetadata, FeedStatus, ProjectMetadata, ProjectStatus
from gtfs_explorer.infrastructure.duckdb.database import (
    DatabaseSchemaError,
    DatabaseSettings,
    MigrationError,
    ProjectDatabase,
)
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    save_project_descriptor,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "src" / "gtfs_explorer" / "infrastructure" / "duckdb" / "migrations"
SETTINGS = DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1)


def _database(project: Path, migrations_directory: Path | None = None) -> ProjectDatabase:
    return ProjectDatabase(
        project / "data.duckdb",
        project / "temp",
        settings=SETTINGS,
        migrations_directory=migrations_directory,
    )


def _schema_9_migrations(project: Path) -> Path:
    directory = project / "migrations-9"
    directory.mkdir()
    for migration in sorted(MIGRATIONS.glob("00[1-9]_*.sql")):
        shutil.copy2(migration, directory / migration.name)
    return directory


def _create_schema_9_project(project: Path, *, legacy_validation: bool = False) -> None:
    project.mkdir()
    migrations = _schema_9_migrations(project)
    assert _database(project, migrations).initialize() == 9
    now = datetime(2026, 9, 22, 10, 0, 0)
    with duckdb.connect(str(project / "data.duckdb")) as connection:
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
            ["project-1", "Demo", "READY", now, now, 9],
        )
        connection.execute(
            "INSERT INTO feeds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "feed-1",
                "project-1",
                "demo.zip",
                "a" * 64,
                "strict",
                "2026-04-27",
                "0.2.1",
                now,
                "IMPORTED",
            ],
        )
        if legacy_validation:
            connection.execute(
                "INSERT INTO validation_runs VALUES (?, ?, ?, ?, ?, ?)",
                ["legacy", "feed-1", "INVALID", 72_608, 10_000, 62_608],
            )
    save_project_descriptor(
        project / "project.json",
        ProjectDescriptor.from_metadata(
            ProjectMetadata("project-1", "Demo", ProjectStatus.READY),
            FeedMetadata(
                "feed-1",
                "project-1",
                "demo.zip",
                "a" * 64,
                "strict",
                "2026-04-27",
                FeedStatus.IMPORTED,
            ),
            project,
        ),
    )


def _schema_version(project: Path) -> int:
    with duckdb.connect(str(project / "data.duckdb"), read_only=True) as connection:
        row = connection.execute("SELECT schema_version FROM schema_metadata").fetchone()
    assert row is not None
    return int(row[0])


def _database_fingerprint(project: Path) -> tuple[str, int, int]:
    path = project / "data.duckdb"
    stat = path.stat()
    return sha256(path.read_bytes()).hexdigest(), stat.st_mtime_ns, stat.st_size


def test_open_project_migrates_schema_9_preserves_legacy_history_and_is_idempotent(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _create_schema_9_project(project, legacy_validation=True)

    with OpenProject(project).execute() as opened:
        assert opened.directory == project
        assert _schema_version(project) == 11

    with duckdb.connect(str(project / "data.duckdb"), read_only=True) as connection:
        assert connection.execute("SELECT schema_version FROM projects").fetchone() == (11,)
        assert connection.execute(
            "SELECT detected_issue_count, persisted_issue_count, detail_complete, legacy_truncated "
            "FROM validation_run_metadata WHERE batch_id = 'legacy'"
        ).fetchone() == (72_608, 0, False, True)
        assert connection.execute(
            "SELECT count(*) FROM schema_migrations WHERE version = 11"
        ).fetchone() == (1,)

    with OpenProject(project).execute() as opened:
        assert opened.directory == project

    with duckdb.connect(str(project / "data.duckdb"), read_only=True) as connection:
        assert connection.execute(
            "SELECT count(*) FROM schema_migrations WHERE version = 11"
        ).fetchone() == (1,)
    assert json.loads((project / "project.json").read_text(encoding="utf-8"))["version"] == 1
    assert not (project / ".writer.lock").exists()


def test_schema_11_repairs_occurrence_metadata_already_written_by_schema_10(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _create_schema_9_project(project)
    migrations = _schema_9_migrations(tmp_path)
    shutil.copy2(
        MIGRATIONS / "010_validation_scalability.sql", migrations / "010_validation_scalability.sql"
    )
    database = _database(project, migrations)
    assert database.initialize() == 10
    with duckdb.connect(str(project / "data.duckdb")) as connection:
        connection.execute(
            "INSERT INTO validation_runs VALUES ('run', 'feed-1', 'INVALID', 3, 1, 2)"
        )
        connection.execute(
            "INSERT INTO validation_issues VALUES "
            "('run', 1, 'fingerprint', 'validator', 'RULE', 'ERROR', 'FIELD', "
            "'stops.txt', 2, 'stop_id', 'stop', 'S1', 'message.key', '{}', 'help', 3)"
        )
        connection.execute(
            "INSERT INTO validation_run_metadata VALUES "
            "('run', 'COMPLETED', 'INVALID', 3, 1, FALSE, TRUE, now(), now())"
        )
    shutil.copy2(
        MIGRATIONS / "011_validation_occurrence_metadata_repair.sql",
        migrations / "011_validation_occurrence_metadata_repair.sql",
    )
    assert database.initialize() == 11
    with duckdb.connect(str(project / "data.duckdb"), read_only=True) as connection:
        assert connection.execute(
            "SELECT detected_issue_count, persisted_issue_count, detail_complete, legacy_truncated "
            "FROM validation_run_metadata WHERE batch_id = 'run'"
        ).fetchone() == (3, 3, True, False)


def test_schema_10_counts_persisted_occurrences_not_detail_rows(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _create_schema_9_project(project)
    with duckdb.connect(str(project / "data.duckdb")) as connection:
        connection.execute(
            "INSERT INTO validation_runs VALUES ('run', 'feed-1', 'INVALID', 3, 1, 2)"
        )
        connection.execute(
            "INSERT INTO validation_issues VALUES "
            "('run', 1, 'fingerprint', 'validator', 'RULE', 'ERROR', 'FIELD', "
            "'stops.txt', 2, 'stop_id', 'stop', 'S1', 'message.key', '{}', 'help', 3)"
        )
    migrations = _schema_9_migrations(tmp_path)
    shutil.copy2(
        MIGRATIONS / "010_validation_scalability.sql", migrations / "010_validation_scalability.sql"
    )
    database = _database(project, migrations)
    assert database.initialize() == 10
    with duckdb.connect(str(project / "data.duckdb"), read_only=True) as connection:
        assert connection.execute(
            "SELECT detected_issue_count, persisted_issue_count, detail_complete, legacy_truncated "
            "FROM validation_run_metadata WHERE batch_id = 'run'"
        ).fetchone() == (3, 3, True, False)


def test_open_project_reconciles_stale_current_schema_mirror_without_reapplying_migration(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _create_schema_9_project(project)
    assert _database(project).initialize() == 11
    with duckdb.connect(str(project / "data.duckdb")) as connection:
        connection.execute("UPDATE projects SET schema_version = 10")
    stale_fingerprint = _database_fingerprint(project)

    with OpenProject(project).execute():
        pass
    reconciled_fingerprint = _database_fingerprint(project)

    with duckdb.connect(str(project / "data.duckdb"), read_only=True) as connection:
        assert connection.execute("SELECT schema_version FROM projects").fetchone() == (11,)
        assert connection.execute(
            "SELECT count(*) FROM schema_migrations WHERE version = 11"
        ).fetchone() == (1,)
    assert reconciled_fingerprint != stale_fingerprint

    with OpenProject(project).execute():
        pass
    assert _database_fingerprint(project) == reconciled_fingerprint


def test_current_database_initialize_and_mirror_sync_are_physically_read_only(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _create_schema_9_project(project)
    database = _database(project)
    assert database.initialize() == 11
    database.synchronize_schema_mirror()
    before = _database_fingerprint(project)

    assert database.initialize() == 11
    database.synchronize_schema_mirror()

    assert _database_fingerprint(project) == before


def test_future_schema_is_rejected_by_initialize_and_real_open_without_mutation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _create_schema_9_project(project)
    assert _database(project).initialize() == 11
    _database(project).backup_path.unlink()
    now = datetime(2026, 9, 22, 10, 0, 0)
    with duckdb.connect(str(project / "data.duckdb")) as connection:
        connection.execute("INSERT INTO schema_migrations VALUES (?, ?)", [12, now])
        connection.execute("UPDATE schema_metadata SET schema_version = 12")

    with pytest.raises(DatabaseSchemaError):
        _database(project).initialize()
    with pytest.raises(DatabaseSchemaError):
        OpenProject(project).execute()

    assert _schema_version(project) == 12
    assert not (project / ".writer.lock").exists()


def test_failed_migration_in_real_open_rolls_back_and_releases_writer_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    _create_schema_9_project(project)
    broken_migrations = _schema_9_migrations(tmp_path)
    (broken_migrations / "010_validation_scalability.sql").write_text(
        "CREATE TABLE migration_should_rollback (id INTEGER); BROKEN SQL;", encoding="utf-8"
    )
    original_database = ProjectDatabase

    def database_with_broken_migration(
        database_path: Path, temporary_directory: Path, *, settings: DatabaseSettings
    ) -> ProjectDatabase:
        return original_database(
            database_path,
            temporary_directory,
            settings=settings,
            migrations_directory=broken_migrations,
        )

    monkeypatch.setattr(open_project_module, "ProjectDatabase", database_with_broken_migration)

    with pytest.raises(MigrationError):
        OpenProject(project).execute()

    assert _schema_version(project) == 9
    with duckdb.connect(str(project / "data.duckdb"), read_only=True) as connection:
        assert connection.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'migration_should_rollback'"
        ).fetchone() == (0,)
    writer_lock = ProjectWriterLock(project)
    writer_lock.acquire()
    writer_lock.release()
    assert not (project / ".writer.lock").exists()
