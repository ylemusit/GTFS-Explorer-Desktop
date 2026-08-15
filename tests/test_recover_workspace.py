"""Recuperación conservadora de trabajos y temporales T024."""

from __future__ import annotations

from pathlib import Path

from gtfs_explorer.application.commands.open_project import OpenProject
from gtfs_explorer.application.commands.recover_workspace import RecoverWorkspace
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
from gtfs_explorer.infrastructure.filesystem.workspace_recovery import WorkspaceRecovery


def _database(project: Path) -> ProjectDatabase:
    return ProjectDatabase(
        project / "data.duckdb",
        project / "temp",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )


def _store_interrupted_project(project: Path) -> ProjectDatabase:
    database = _database(project)
    with DuckDbUnitOfWork(database) as unit_of_work:
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
                FeedStatus.FAILED,
            )
        )
        unit_of_work.import_jobs.save_metadata(
            ImportJobMetadata("job-1", "feed-1", JobState.RUNNING, "STAGING", 0.4)
        )
    return database


def test_opening_after_crash_requires_recovery_and_never_keeps_ready(tmp_path: Path) -> None:
    project = tmp_path / "project"
    database = _store_interrupted_project(project)
    leftover = database.temporary_directory / "import-job-1"
    leftover.mkdir(parents=True)
    (leftover / "partial.txt").write_text("incomplete", encoding="utf-8")

    with OpenProject(project).execute():
        pass

    with database.connection() as connection:
        assert connection.execute("SELECT status FROM projects").fetchone() == (
            "RECOVERY_REQUIRED",
        )
        assert connection.execute("SELECT state, error_code FROM import_jobs").fetchone() == (
            "FAILED",
            "INTERRUPTED_RECOVERY",
        )
    quarantined = list((database.temporary_directory / "quarantine").iterdir())
    assert len(quarantined) == 1
    assert not leftover.exists()


def test_cleanup_requires_confirmation_and_reports_exact_deleted_target(tmp_path: Path) -> None:
    database = _store_interrupted_project(tmp_path / "project")
    leftover = database.temporary_directory / "import-job-1"
    leftover.mkdir(parents=True)
    recovery = RecoverWorkspace(database)
    result = recovery.execute()

    assert result.retry_job_ids == ("job-1",)
    assert len(result.actions) == 1
    quarantined = result.actions[0].target
    assert quarantined.is_absolute()
    assert recovery.cleanup_quarantine(confirmed=False) == ()
    assert quarantined.exists()

    actions = recovery.cleanup_quarantine(confirmed=True)

    assert actions[0].kind == "DELETED"
    assert actions[0].target == quarantined
    assert not quarantined.exists()


def test_paths_manipulated_outside_workspace_are_never_removed(tmp_path: Path) -> None:
    database = _store_interrupted_project(tmp_path / "project")
    outside = tmp_path / "project" / "outside"
    outside.mkdir()
    (outside / "preserve.txt").write_text("keep", encoding="utf-8")
    quarantine = database.temporary_directory / "quarantine"
    quarantine.mkdir(parents=True)
    manipulated = quarantine / ".." / ".." / "outside"

    recovery = WorkspaceRecovery(database.temporary_directory)

    assert recovery._verified_child(manipulated, quarantine) is None
    assert (outside / "preserve.txt").exists()
