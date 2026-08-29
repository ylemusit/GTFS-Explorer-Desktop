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
    ProjectDescriptor,
    ProjectDescriptorError,
    ProjectDescriptorMismatchError,
    ProjectDescriptorReconciliation,
    classify_project_descriptor,
    reconcile_project_descriptor,
    save_project_descriptor,
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


def test_legacy_operational_mismatch_is_classified_and_repaired_atomically(tmp_path: Path) -> None:
    project = tmp_path / "project"
    database = _database(project)
    _store(database, "a" * 64)
    legacy = ProjectDescriptor(
        "project-1",
        "Demo",
        "RECOVERY_REQUIRED",
        "old-feed",
        "b" * 64,
        ProjectDescriptor.from_metadata(
            ProjectMetadata("project-1", "Demo", ProjectStatus.READY), None, project
        ).references,
    )
    save_project_descriptor(project / "project.json", legacy)

    with DuckDbUnitOfWork(database) as unit_of_work:
        expected = ProjectDescriptor.from_metadata(
            unit_of_work.projects.metadata(), unit_of_work.feeds.latest_metadata(), project
        )
        assert (
            classify_project_descriptor(legacy, expected)
            is ProjectDescriptorReconciliation.RECOVERABLE_LEGACY_MISMATCH
        )
        assert reconcile_project_descriptor(project, unit_of_work) == expected

    payload = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert payload["name"] == "Demo"
    assert payload["feed"] == {"feed_id": "feed-1", "manifest_sha256": "a" * 64}


def test_atomic_legacy_repair_preserves_original_descriptor_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    database = _database(project)
    _store(database, "a" * 64)
    legacy = ProjectDescriptor.from_metadata(
        ProjectMetadata("project-1", "Demo", ProjectStatus.READY), None, project
    )
    descriptor_path = project / "project.json"
    save_project_descriptor(descriptor_path, legacy)
    original = descriptor_path.read_bytes()

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(
        "gtfs_explorer.infrastructure.filesystem.project_descriptor.os.replace", fail_replace
    )
    with DuckDbUnitOfWork(database) as unit_of_work, pytest.raises(OSError):
        reconcile_project_descriptor(project, unit_of_work)

    assert descriptor_path.read_bytes() == original
    assert not list(project.glob(".project.json.*.tmp"))


def test_project_id_or_name_divergence_is_unrecoverable_and_preserves_descriptor(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    database = _database(project)
    _store(database, "a" * 64)
    with DuckDbUnitOfWork(database) as unit_of_work:
        descriptor = ProjectDescriptor.from_metadata(
            unit_of_work.projects.metadata(), unit_of_work.feeds.latest_metadata(), project
        )
    divergent = ProjectDescriptor(
        "another-project",
        descriptor.name,
        descriptor.status,
        descriptor.feed_id,
        descriptor.feed_sha256,
        descriptor.references,
    )
    descriptor_path = project / "project.json"
    save_project_descriptor(descriptor_path, divergent)
    original = descriptor_path.read_bytes()

    with DuckDbUnitOfWork(database) as unit_of_work, pytest.raises(ProjectDescriptorMismatchError):
        reconcile_project_descriptor(project, unit_of_work)

    assert descriptor_path.read_bytes() == original


def test_unknown_operational_status_is_unrecoverable(tmp_path: Path) -> None:
    project = tmp_path / "project"
    database = _database(project)
    _store(database, "a" * 64)
    with DuckDbUnitOfWork(database) as unit_of_work:
        descriptor = ProjectDescriptor.from_metadata(
            unit_of_work.projects.metadata(), unit_of_work.feeds.latest_metadata(), project
        )
    divergent = ProjectDescriptor(
        descriptor.project_id,
        descriptor.name,
        "UNKNOWN",
        descriptor.feed_id,
        descriptor.feed_sha256,
        descriptor.references,
    )
    descriptor_path = project / "project.json"
    save_project_descriptor(descriptor_path, divergent)
    original = descriptor_path.read_bytes()

    with DuckDbUnitOfWork(database) as unit_of_work, pytest.raises(ProjectDescriptorMismatchError):
        reconcile_project_descriptor(project, unit_of_work)

    assert descriptor_path.read_bytes() == original
