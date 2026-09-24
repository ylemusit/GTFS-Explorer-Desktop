"""Integración del orquestador recuperable de importación T018."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from gtfs_explorer.application.commands.import_feed import ImportFeed
from gtfs_explorer.application.jobs.import_job import CancelToken, ImportPhase
from gtfs_explorer.application.queries.raw import RawInspectorQueries
from gtfs_explorer.domain.operations import OperationStatus
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.domain.project import FeedStatus, JobState, ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.raw import RawQuery
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.duckdb.repositories.base import DuckDbRawInspectorRepository
from gtfs_explorer.infrastructure.logging import configure_logging
from gtfs_explorer.infrastructure.validation.engine import ValidationEngine

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

    database = _database(tmp_path)
    result = _command(database, source).execute()

    assert result.state is JobState.READY
    assert result.issue_count == 0
    with database.connection() as connection:
        assert connection.execute("SELECT status FROM feeds").fetchone() == ("IMPORTED",)
        assert connection.execute("SELECT count(*) FROM operations").fetchone() == (1,)
        assert connection.execute(
            "SELECT o.status, d.feed_id, d.job_id "
            "FROM operations o JOIN operation_import_details d "
            "ON d.operation_id = o.operation_id"
        ).fetchone() == (OperationStatus.COMPLETED.value, "feed-1", "job-1")
    with DuckDbUnitOfWork(database) as unit_of_work:
        operation = unit_of_work.operations.list_operations("project-1", PageRequest()).items[0]
    assert operation.operation_type.value == "IMPORT"
    assert operation.validation_batch_id == "job-1:structure"
    assert operation.validation_result == "VALID"
    assert operation.validation_issue_count == 1


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
        assert connection.execute("SELECT status FROM feeds").fetchone() == ("IMPORTED",)
        assert connection.execute("SELECT status FROM validation_runs").fetchone() == ("INVALID",)
        assert connection.execute("SELECT count(*) FROM normalization_issues").fetchone()[0] > 0
        assert connection.execute("SELECT status FROM operations").fetchone() == (
            OperationStatus.COMPLETED.value,
        )
        assert connection.execute("SELECT count(*) FROM operations").fetchone() == (1,)

    with DuckDbUnitOfWork(database) as unit_of_work:
        operation = unit_of_work.operations.list_operations("project-1", PageRequest()).items[0]
    assert operation.operation_type.value == "IMPORT"
    assert operation.validation_batch_id == "job-1:structure"
    assert operation.validation_result == "INVALID"
    assert operation.validation_issue_count is not None

    with DuckDbUnitOfWork(database) as unit_of_work:
        feed = unit_of_work.feeds.latest_metadata()
        assert feed is not None
        assert feed.status is FeedStatus.IMPORTED
        assert unit_of_work.overview.overview().feed == feed


@pytest.mark.integration
def test_blank_physical_lines_are_ignored_without_failed_import_and_remain_inspectable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    stops = source / "stops.txt"
    stops.write_text(
        "stop_id,stop_name,stop_lat,stop_lon\n\nS1,Norte,43.1,-5.8\n\n\nS2,Sur,43.2,-5.9\n",
        encoding="utf-8",
    )

    database = _database(tmp_path)
    result = _command(database, source).execute()

    assert result.state is not JobState.FAILED
    with database.connection() as connection:
        assert connection.execute("SELECT status FROM feeds").fetchone() == ("IMPORTED",)
        assert connection.execute("SELECT count(*) FROM stg_stops").fetchone() == (2,)
        assert connection.execute(
            "SELECT loaded_row_count FROM stg_source_inventory WHERE original_name = 'stops.txt'"
        ).fetchone() == (2,)
        raw = RawInspectorQueries(
            DuckDbRawInspectorRepository(connection, load_schedule_spec(SPEC_PATH))
        ).query(RawQuery("stops.txt", ("stop_id", "stop_name")))

    assert [(row.source_row, row.values) for row in raw.rows] == [
        (3, ("S1", "Norte")),
        (6, ("S2", "Sur")),
    ]


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
def test_first_cancellation_is_cancelled_not_failed_and_has_no_validation_result(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    token = CancelToken()

    def cancel_at_progress(progress: object) -> None:
        if getattr(progress, "phase") is ImportPhase.NORMALIZING:
            token.cancel()

    database = _database(tmp_path)
    result = _command(database, source, on_progress=cancel_at_progress).execute(token)

    assert result.state is JobState.CANCELLED
    with database.connection() as connection:
        assert connection.execute("SELECT status FROM feeds").fetchone() == ("CANCELLED",)
        assert connection.execute("SELECT state FROM import_jobs").fetchone() == ("CANCELLED",)
        assert connection.execute("SELECT count(*) FROM validation_runs").fetchone() == (0,)
        assert connection.execute("SELECT started_at, finished_at FROM import_jobs").fetchone() == (
            None,
            None,
        )
        assert connection.execute("SELECT status, error_code FROM operations").fetchone() == (
            OperationStatus.CANCELLED.value,
            "CANCELLED",
        )
    with DuckDbUnitOfWork(database) as unit_of_work:
        operation = unit_of_work.operations.list_operations("project-1", PageRequest()).items[0]
    assert operation.operation_type.value == "IMPORT"
    assert operation.validation_batch_id is None
    assert operation.validation_result is None
    assert operation.validation_issue_count is None


@pytest.mark.integration
def test_reimport_cancellation_keeps_previous_imported_feed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    database = _database(tmp_path)
    assert _command(database, source).execute().state is JobState.READY

    token = CancelToken()
    token.cancel()
    cancelled = ImportFeed(
        database,
        _project(),
        InputSource(source, InputSourceKind.DIRECTORY),
        load_schedule_spec(SPEC_PATH),
        job_id="job-2",
        feed_id="feed-2",
    ).execute(token)

    assert cancelled.state is JobState.CANCELLED
    with DuckDbUnitOfWork(database) as unit_of_work:
        feed = unit_of_work.feeds.latest_metadata()
        assert feed is not None
        assert feed.status is FeedStatus.IMPORTED
    with database.connection() as connection:
        assert connection.execute(
            "SELECT status FROM feeds WHERE feed_id = 'feed-2' ORDER BY imported_at DESC LIMIT 1"
        ).fetchone() == ("CANCELLED",)


@pytest.mark.integration
def test_cancellation_during_validation_persists_cancelled_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    token = CancelToken()
    original_execute = ValidationEngine.execute

    def cancel_inside_validation(self: object, connection: object, **kwargs: object) -> object:
        token.cancel()
        return original_execute(self, connection, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ValidationEngine, "execute", cancel_inside_validation)
    database = _database(tmp_path)
    result = _command(database, source).execute(token)

    assert result.state is JobState.CANCELLED
    with database.connection() as connection:
        assert connection.execute("SELECT status FROM validation_runs").fetchone() == ("CANCELLED",)
        assert connection.execute("SELECT status FROM feeds").fetchone() == ("CANCELLED",)


@pytest.mark.integration
def test_validation_failure_has_no_fictitious_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)

    def fail_persist(*args: object, **kwargs: object) -> None:
        raise RuntimeError("fallo de persistencia de validación")

    monkeypatch.setattr(ValidationEngine, "_persist", staticmethod(fail_persist))
    database = _database(tmp_path)
    result = _command(database, source).execute()

    assert result.state is JobState.FAILED
    with DuckDbUnitOfWork(database) as unit_of_work:
        operation = unit_of_work.operations.list_operations("project-1", PageRequest()).items[0]
    assert operation.operation_type.value == "IMPORT"
    assert operation.validation_batch_id == "job-1:structure"
    assert operation.validation_result is None
    assert operation.validation_issue_count is None


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
        assert connection.execute("SELECT status, error_code FROM operations").fetchone() == (
            OperationStatus.FAILED.value,
            "IMPORTSECURITYERROR",
        )


@pytest.mark.integration
def test_gtfs_023_synthetic_large_enum_fixture_has_no_false_normalization_issues(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    for filename, fields in {
        "stops.txt": {"wheelchair_boarding": "0"},
        "routes.txt": {"continuous_pickup": "1", "continuous_drop_off": "1"},
        "stop_times.txt": {"continuous_pickup": "1", "continuous_drop_off": "1"},
    }.items():
        path = source / filename
        with path.open(encoding="utf-8", newline="") as input_file:
            rows = list(csv.DictReader(input_file))
            headers = [*rows[0], *fields]
        for row in rows:
            row.update(fields)
        if filename == "stop_times.txt":
            rows = [
                dict(row, stop_sequence=str(index + 1)) for index, row in enumerate(rows * 1001)
            ]
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    database = _database(tmp_path)
    result = _command(database, source).execute()

    assert result.state is not JobState.FAILED
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM stg_stop_times").fetchone()[0] > 1_000
        assert connection.execute(
            "SELECT count(*) FROM normalization_issues "
            "WHERE issue_code = 'GTFS_TYPE_CONVERSION_INVALID' "
            "AND field_name IN ('continuous_pickup', 'continuous_drop_off', 'wheelchair_boarding')"
        ).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM validation_runs").fetchone() == (1,)


@pytest.mark.integration
def test_import_failure_logs_sanitized_context_traceback_and_cause(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)

    def fail_persist(*args: object, **kwargs: object) -> None:
        try:
            raise ValueError("token=synthetic-secret")
        except ValueError as cause:
            raise RuntimeError("validation failed at C:/private/feed.zip") from cause

    monkeypatch.setattr(ValidationEngine, "_persist", staticmethod(fail_persist))
    logger = configure_logging(tmp_path / "logs")
    try:
        result = _command(_database(tmp_path), source).execute()
        logger.handlers[0].flush()
        content = (tmp_path / "logs" / "gtfs-explorer.log").read_text(encoding="utf-8")
    finally:
        for handler in logger.handlers:
            handler.close()

    assert result.state is JobState.FAILED
    assert "operation': 'import_feed'" in content
    assert "job_id': 'job-1'" in content and "feed_id': 'feed-1'" in content
    assert "phase': 'VALIDATING'" in content
    assert "RuntimeError" in content and "ValueError" in content
    assert "Traceback (most recent call last)" in content
    assert "synthetic-secret" not in content and "C:/private/feed.zip" not in content
