"""Contratos automatizables de compatibilidad y upgrade P1-33."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from gtfs_explorer.application.settings import DirectoryPreferences, Settings, save_settings
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.filesystem.paths import ApplicationPaths

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_FIXTURE = ROOT / "tests" / "fixtures" / "historical" / "p1-32"
ARTIFACT_STORE_ENV = "GTFS_EXPLORER_ARTIFACT_STORE"
ARTIFACT_RELEASE = Path("acceptance-builds") / "P1-32-packaging-20260828"
MIGRATIONS = ROOT / "src" / "gtfs_explorer" / "infrastructure" / "duckdb" / "migrations"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _database(root: Path, migrations: Path | None = None) -> ProjectDatabase:
    return ProjectDatabase(
        root / "data.duckdb",
        root / "temp",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
        migrations_directory=migrations,
    )


def _make_schema_8_project(root: Path) -> None:
    schema_8 = root / "migrations-8"
    schema_8.mkdir()
    for path in sorted(MIGRATIONS.glob("00[1-8]_*.sql")):
        shutil.copy2(path, schema_8 / path.name)
    database = _database(root, schema_8)
    assert database.initialize() == 8
    now = datetime(2026, 8, 28, 10, 0, 0)
    with duckdb.connect(str(database.database_path)) as connection:
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
            ["legacy-project", "Proyecto legacy", "READY", now, now, 8],
        )
        connection.execute(
            "INSERT INTO feeds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "legacy-feed",
                "legacy-project",
                "feed.zip",
                "a" * 64,
                "directory",
                "2026-04-27",
                "0.1.0",
                now,
                "IMPORTED",
            ],
        )
        connection.execute(
            "INSERT INTO import_jobs "
            "(job_id, feed_id, state, started_at, finished_at, progress, error_code, phase) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["legacy-job", "legacy-feed", "INVALID", now, now, 1.0, None, "VALIDATING"],
        )


def _expected_p1_32_artifacts(manifest_path: Path) -> dict[str, str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = {item["file"]: item["sha256"] for item in manifest["artifacts"]}
    return actual


def test_p1_32_historical_manifest_fixture_has_the_recorded_artifact_hashes() -> None:
    expected = {
        (
            "GTFS-Explorer-Setup-0.1.0-P1-32-packaging-20260828-win-x64.exe"
        ): "54297c2695327697a6e1091bf36b42f2f34ef588bf8b93a8c027eb9ca71735ec",
        (
            "GTFS-Explorer-Portable-0.1.0-P1-32-packaging-20260828-win-x64.zip"
        ): "8450d974df386ff6d1b1d852febbf9bb78e031493c5246be5e44e3d46232f050",
    }
    assert _expected_p1_32_artifacts(HISTORICAL_FIXTURE / "release-manifest.json") == expected


@pytest.mark.artifact_dependent
def test_p1_33_target_artifacts_match_manifest() -> None:
    artifact_store = os.environ.get(ARTIFACT_STORE_ENV)
    if artifact_store is None:
        pytest.skip(f"requiere {ARTIFACT_STORE_ENV} con el release histórico P1-32")
    target = Path(artifact_store) / ARTIFACT_RELEASE
    expected = _expected_p1_32_artifacts(HISTORICAL_FIXTURE / "release-manifest.json")
    assert _expected_p1_32_artifacts(target / "release-manifest.json") == expected
    for filename, digest in expected.items():
        assert _sha256(target / filename) == digest


def test_legacy_schema_8_migrates_with_data_and_is_idempotent(tmp_path: Path) -> None:
    _make_schema_8_project(tmp_path)
    database = _database(tmp_path)
    before = (tmp_path / "data.duckdb").read_bytes()

    assert database.initialize() == 9
    backup = database.backup_path
    assert backup.read_bytes() == before
    with database.connection() as connection:
        assert connection.execute("SELECT schema_version FROM schema_metadata").fetchone() == (9,)
        assert connection.execute("SELECT project_id, name FROM projects").fetchone() == (
            "legacy-project",
            "Proyecto legacy",
        )
        assert connection.execute("SELECT feed_id, status FROM feeds").fetchone() == (
            "legacy-feed",
            "IMPORTED",
        )
        assert connection.execute("SELECT state FROM import_jobs").fetchone() == ("INVALID",)
        assert connection.execute("SELECT count(*) FROM operations").fetchone() == (0,)
    migrated = (tmp_path / "data.duckdb").read_bytes()
    assert database.initialize() == 9
    assert (tmp_path / "data.duckdb").read_bytes() == migrated


def test_failed_schema_8_upgrade_preserves_original_and_recovery_backup(tmp_path: Path) -> None:
    _make_schema_8_project(tmp_path)
    broken = tmp_path / "broken-migrations"
    shutil.copytree(tmp_path / "migrations-8", broken)
    (broken / "009_operations_history.sql").write_text("BROKEN SQL;", encoding="utf-8")
    database = _database(tmp_path, broken)
    before = (tmp_path / "data.duckdb").read_bytes()

    try:
        database.initialize()
    except Exception as error:
        assert type(error).__name__ == "MigrationError"
    else:
        raise AssertionError("La migración rota debía fallar de forma controlada")
    assert (tmp_path / "data.duckdb").read_bytes() == before
    assert database.backup_path.read_bytes() == before


def test_settings_and_maps_are_outside_install_payload_and_preserved(tmp_path: Path) -> None:
    documents = tmp_path / "Documents"
    local_app_data = tmp_path / "LocalAppData"
    paths = ApplicationPaths(tmp_path / "app-data", False, documents)
    paths.create_directories()
    settings = Settings(
        last_project_dir=documents / "GTFS Explorer" / "Projects",
        last_import_dir=documents / "GTFS Explorer" / "Imports",
        last_export_dir=documents / "GTFS Explorer" / "Exports",
    )
    save_settings(paths.settings_path, settings)
    maps = paths.maps_directory
    maps.mkdir(parents=True)
    marker = maps / "offline-package.pmtiles"
    marker.write_bytes(b"fixture")
    install_payload = tmp_path / "install"
    install_payload.mkdir()
    (install_payload / "GTFS Explorer.exe").write_bytes(b"target")

    preferences = DirectoryPreferences(paths)
    assert preferences.settings.last_project_dir == settings.last_project_dir
    assert marker.read_bytes() == b"fixture"
    assert not (local_app_data / "GTFS Explorer").exists()
