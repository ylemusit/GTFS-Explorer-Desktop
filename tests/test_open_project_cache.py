from __future__ import annotations

import json
import os
import threading
from hashlib import sha256
from pathlib import Path

import pytest

from gtfs_explorer.application.commands.open_project import (
    OpenProject,
    ProjectWriterLockedError,
)
from gtfs_explorer.domain.project import (
    FeedMetadata,
    FeedStatus,
    ProjectMetadata,
    ProjectStatus,
)
from gtfs_explorer.infrastructure.duckdb.database import (
    DatabaseCorruptionError,
    DatabaseSchemaError,
    DatabaseSettings,
    ProjectDatabase,
)
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.cache import CacheKey, CacheStore
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    save_project_descriptor,
)


def _database(project: Path) -> ProjectDatabase:
    return ProjectDatabase(
        project / "data.duckdb",
        project / "temp",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )


def _store_project(project: Path) -> None:
    with DuckDbUnitOfWork(_database(project)) as unit_of_work:
        unit_of_work.projects.save_metadata(
            ProjectMetadata("project-1", "Demo", ProjectStatus.READY)
        )
        unit_of_work.feeds.save_metadata(
            FeedMetadata(
                "feed-1",
                "project-1",
                "demo.zip",
                "a" * 64,
                "strict",
                "2026-04-27",
                FeedStatus.IMPORTED,
            )
        )


def _key() -> CacheKey:
    return CacheKey("a" * 64, "query-v1", {"route_ids": ["R1"]}, {"format": "geojson"})


def test_old_cache_format_is_ignored_and_discarded(tmp_path: Path) -> None:
    cache = CacheStore(tmp_path / "cache")
    key = _key()
    cache.write(key, b"old-derived-value")

    newer_cache = CacheStore(cache.directory, format_version=2)

    assert newer_cache.read(key) is None
    assert not list(cache.directory.glob("*.cache.json"))


def test_second_local_writer_is_blocked_with_pid_message(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _store_project(project)
    first = OpenProject(project).execute()
    result: list[BaseException] = []

    def open_second_writer() -> None:
        try:
            OpenProject(project).execute()
        except BaseException as error:
            result.append(error)

    thread = threading.Thread(target=open_second_writer)
    thread.start()
    thread.join()
    first.close()

    assert len(result) == 1
    assert isinstance(result[0], ProjectWriterLockedError)
    assert f"PID {os.getpid()}" in str(result[0])


def test_reader_observes_previous_complete_cache_entry_while_new_entry_is_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = CacheStore(tmp_path / "cache")
    key = _key()
    cache.write(key, b"complete-old-value")
    observed: list[bytes | None] = []
    replace = os.replace

    def observe_before_replace(source: Path | str, destination: Path | str) -> None:
        observed.append(cache.read(key))
        replace(source, destination)

    monkeypatch.setattr(
        "gtfs_explorer.infrastructure.filesystem.cache.os.replace", observe_before_replace
    )
    cache.write(key, b"complete-new-value")

    assert observed == [b"complete-old-value"]
    assert cache.read(key) == b"complete-new-value"


def test_clearing_cache_preserves_imported_project_data(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _store_project(project)

    with OpenProject(project).execute() as opened:
        opened.cache.write(_key(), b"discardable-derivative")
        opened.cache.clear()
        assert opened.cache.read(_key()) is None

    with (
        OpenProject(project).execute() as reopened,
        DuckDbUnitOfWork(reopened.database) as unit_of_work,
    ):
        feed = unit_of_work.feeds.latest_metadata()

    assert feed is not None
    assert feed.feed_id == "feed-1"


def test_reopening_same_project_for_two_cycles_preserves_persisted_feed_and_workspace(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _store_project(project)
    with OpenProject(project).execute() as opened:
        opened.close()
        opened.close()

    before = {
        name: sha256((project / name).read_bytes()).hexdigest()
        for name in ("project.json", "data.duckdb")
    }
    cache_existed_before = (project / "cache").exists()
    for _ in range(2):
        with OpenProject(project).execute() as opened:
            with DuckDbUnitOfWork(opened.database) as unit_of_work:
                feed = unit_of_work.feeds.latest_metadata()
                assert feed is not None
                assert feed.feed_id == "feed-1"

    after = {
        name: sha256((project / name).read_bytes()).hexdigest()
        for name in ("project.json", "data.duckdb")
    }
    assert after == before
    assert (project / "temp").is_dir()
    assert (project / "cache").exists() is cache_existed_before


def test_pre_fix_descriptor_with_imported_feed_is_repaired_without_reimporting(
    tmp_path: Path,
) -> None:
    """Fija el comportamiento actual ante el proyecto legacy que provocaba UI-0003.

    El build anterior podía crear el descriptor antes de persistir el feed y no
    actualizarlo después. Por tanto ``project.json`` conserva ``feed: null``
    mientras DuckDB ya contiene los metadatos importados.
    """
    project = tmp_path / "legacy-project"
    project.mkdir()
    database = _database(project)
    with DuckDbUnitOfWork(database) as unit_of_work:
        unit_of_work.projects.save_metadata(
            ProjectMetadata("project-1", "Demo", ProjectStatus.READY)
        )

    # Simula el descriptor escrito por el build pre-fix antes de la importación.
    save_project_descriptor(
        project / "project.json",
        ProjectDescriptor.from_metadata(
            ProjectMetadata("project-1", "Demo", ProjectStatus.READY), None, project
        ),
    )
    with DuckDbUnitOfWork(database) as unit_of_work:
        unit_of_work.feeds.save_metadata(
            FeedMetadata(
                "feed-1",
                "project-1",
                "legacy-feed.zip",
                "a" * 64,
                "strict",
                "2026-04-27",
                FeedStatus.IMPORTED,
            )
        )

    assert json.loads((project / "project.json").read_text(encoding="utf-8"))["feed"] is None

    # La primera apertura repara exclusivamente los campos operativos. Los
    # ciclos posteriores no vuelven a escribir ni requieren reimportación.
    for _ in range(3):
        with OpenProject(project).execute() as opened:
            with DuckDbUnitOfWork(opened.database) as unit_of_work:
                feed = unit_of_work.feeds.latest_metadata()
                assert feed is not None
                assert feed.feed_id == "feed-1"
        assert not (project / ".writer.lock").exists()

    payload = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert payload["status"] == "READY"
    assert payload["feed"] == {"feed_id": "feed-1", "manifest_sha256": "a" * 64}


def test_corrupt_duckdb_does_not_repair_or_truncate_descriptor(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _store_project(project)
    with DuckDbUnitOfWork(_database(project)) as unit_of_work:
        save_project_descriptor(
            project / "project.json",
            ProjectDescriptor.from_metadata(
                unit_of_work.projects.metadata(), unit_of_work.feeds.latest_metadata(), project
            ),
        )
    descriptor_path = project / "project.json"
    original = descriptor_path.read_bytes()
    (project / "data.duckdb").write_bytes(b"not a DuckDB database")

    with pytest.raises(DatabaseCorruptionError):
        OpenProject(project).execute()

    assert descriptor_path.read_bytes() == original
    assert not (project / ".writer.lock").exists()


def test_incompatible_duckdb_does_not_repair_descriptor(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _store_project(project)
    with DuckDbUnitOfWork(_database(project)) as unit_of_work:
        save_project_descriptor(
            project / "project.json",
            ProjectDescriptor.from_metadata(
                unit_of_work.projects.metadata(), unit_of_work.feeds.latest_metadata(), project
            ),
        )
    descriptor_path = project / "project.json"
    original = descriptor_path.read_bytes()
    with _database(project).connection() as connection:
        connection.execute("UPDATE schema_metadata SET schema_version = 999")

    with pytest.raises(DatabaseSchemaError):
        OpenProject(project).execute()

    assert descriptor_path.read_bytes() == original
    assert not (project / ".writer.lock").exists()
