from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from gtfs_explorer.application.commands.open_project import (
    OpenProject,
    ProjectWriterLockedError,
)
from gtfs_explorer.domain.project import FeedMetadata, FeedStatus, ProjectMetadata, ProjectStatus
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.cache import CacheKey, CacheStore


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
