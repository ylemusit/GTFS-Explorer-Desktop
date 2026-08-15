"""Integración del orquestador recuperable de importación T018."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from gtfs_explorer.application.commands.import_feed import ImportFeed
from gtfs_explorer.application.jobs.import_job import CancelToken, ImportPhase
from gtfs_explorer.domain.project import JobState, ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase

SPEC_PATH = Path("schemas/gtfs_schedule/2026-04-27/spec.json")


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )


def _project() -> ProjectMetadata:
    return ProjectMetadata("project-1", "Demo", ProjectStatus.READY)


def _write_fixture(source: Path) -> None:
    fixture = json.loads((Path("tests/fixtures/specs/valid_full.json")).read_text(encoding="utf-8"))
    for filename, table in fixture["tables"].items():
        with (source / filename).open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=table["headers"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(table["rows"])


def _command(database: ProjectDatabase, source: Path, **kwargs: object) -> ImportFeed:
    return ImportFeed(
        database,
        _project(),
        InputSource(source, InputSourceKind.DIRECTORY),
        load_schedule_spec(SPEC_PATH),
        job_id="job-1",
        feed_id="feed-1",
        **kwargs,
    )


@pytest.mark.integration
def test_success_is_ready_only_after_all_phases_commit(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)

    result = _command(_database(tmp_path), source).execute()

    assert result.state is JobState.READY
    assert result.issue_count == 0


@pytest.mark.integration
def test_validation_errors_finish_invalid_never_ready(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "routes.txt").write_text("route_id,route_type\nR1,bus\n", encoding="utf-8")

    database = _database(tmp_path)
    result = _command(database, source).execute()

    assert result.state is JobState.INVALID
    with database.connection() as connection:
        assert connection.execute("SELECT state FROM import_jobs").fetchone() == ("INVALID",)
        assert connection.execute("SELECT count(*) FROM normalization_issues").fetchone()[0] > 0


@pytest.mark.integration
@pytest.mark.parametrize("phase", tuple(ImportPhase)[:-1])
def test_cancellation_is_reproducible_at_every_work_phase(
    tmp_path: Path, phase: ImportPhase
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    token = CancelToken()

    def cancel_at_progress(progress: object) -> None:
        if getattr(progress, "phase") is phase:
            token.cancel()

    result = _command(_database(tmp_path), source, on_progress=cancel_at_progress).execute(token)

    assert result.state is JobState.CANCELLED


@pytest.mark.integration
def test_simulated_disk_failure_finishes_failed_and_cleans_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "feed.zip"
    with ZipFile(archive, "w") as output:
        output.writestr("routes.txt", "route_id,route_type\nR1,3\n")
    database = _database(tmp_path)
    command = ImportFeed(
        database,
        _project(),
        InputSource(archive, InputSourceKind.ARCHIVE),
        load_schedule_spec(SPEC_PATH),
        job_id="job-1",
        feed_id="feed-1",
        has_free_space=lambda required_bytes: False,
    )

    result = command.execute()

    assert result.state is JobState.FAILED
    assert not (database.temporary_directory / "import-job-1").exists()
    with database.connection() as connection:
        assert connection.execute("SELECT state, error_code FROM import_jobs").fetchone() == (
            "FAILED",
            "ImportSecurityError",
        )
