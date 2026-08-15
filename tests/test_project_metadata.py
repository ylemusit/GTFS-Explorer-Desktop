from __future__ import annotations

import json
from pathlib import Path

import pytest

from gtfs_explorer.domain.project import (
    FeedMetadata,
    FeedStatus,
    ImportJobMetadata,
    JobState,
    ProjectMetadata,
    ProjectStatus,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptorError,
    ProjectDescriptorMismatchError,
    reconcile_project_descriptor,
)


def _database(project: Path) -> ProjectDatabase:
    return ProjectDatabase(
        project / "data.duckdb",
        project / "temp",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )


def _store(database: ProjectDatabase, digest: str) -> None:
    with DuckDbUnitOfWork(database) as unit_of_work:
        unit_of_work.projects.save_metadata(
            ProjectMetadata("project-1", "Demo", ProjectStatus.READY)
        )
        unit_of_work.feeds.save_metadata(
            FeedMetadata(
                "feed-1",
                "project-1",
                "gtfs.zip",
                digest,
                "strict",
                "2026-04-27",
                FeedStatus.IMPORTED,
            )
        )
        unit_of_work.import_jobs.save_metadata(
            ImportJobMetadata("job-1", "feed-1", JobState.SUCCEEDED)
        )


def test_reopening_regenerates_absent_descriptor_from_duckdb_with_relative_paths(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    digest = "a" * 64
    database = _database(project)
    _store(database, digest)

    with DuckDbUnitOfWork(database) as unit_of_work:
        descriptor = reconcile_project_descriptor(project, unit_of_work)
    with DuckDbUnitOfWork(database) as unit_of_work:
        assert reconcile_project_descriptor(project, unit_of_work) == descriptor

    payload = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert payload["feed"]["manifest_sha256"] == digest
    assert payload["references"] == {
        "database": "data.duckdb",
        "cache": "cache",
        "reports": "reports",
    }


@pytest.mark.parametrize("contents", ["{", '{"version": 1}'])
def test_reopening_rejects_invalid_descriptor(tmp_path: Path, contents: str) -> None:
    project = tmp_path / "project"
    database = _database(project)
    _store(database, "a" * 64)
    project.mkdir(exist_ok=True)
    (project / "project.json").write_text(contents, encoding="utf-8")

    with DuckDbUnitOfWork(database) as unit_of_work, pytest.raises(ProjectDescriptorError):
        reconcile_project_descriptor(project, unit_of_work)


def test_feed_with_same_name_but_changed_hash_is_not_confused_on_reopening(tmp_path: Path) -> None:
    project = tmp_path / "project"
    database = _database(project)
    _store(database, "a" * 64)
    with DuckDbUnitOfWork(database) as unit_of_work:
        reconcile_project_descriptor(project, unit_of_work)
    _store(database, "b" * 64)

    with DuckDbUnitOfWork(database) as unit_of_work, pytest.raises(ProjectDescriptorMismatchError):
        reconcile_project_descriptor(project, unit_of_work)
