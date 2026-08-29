"""P1-04A: ledger aislado de operaciones sobre schema 9."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from gtfs_explorer.application.operations import OperationHistory
from gtfs_explorer.domain.operations import (
    OperationDisplayStatus,
    OperationStatus,
    OperationType,
    display_status,
)
from gtfs_explorer.domain.ports import PageRequest
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


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )


def _seed(database: ProjectDatabase) -> None:
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO projects VALUES ('project', 'Proyecto', 'READY', ?, ?, 9)",
            [datetime(2026, 1, 1), datetime(2026, 1, 1)],
        )
        connection.execute(
            "INSERT INTO feeds VALUES ('feed', 'project', 'feed.zip', ?, 'ZIP', '2025', "
            "'test', ?, 'IMPORTED')",
            ["0" * 64, datetime(2026, 1, 1)],
        )
        connection.execute(
            "INSERT INTO import_jobs (job_id, feed_id, state, phase, progress) "
            "VALUES ('job', 'feed', 'READY', 'DONE', 1)"
        )
        connection.execute(
            "INSERT INTO validation_runs VALUES ('batch', 'feed', 'INVALID', 3, 3, 0)"
        )


def test_start_all_types_finish_and_reopen_preserves_utc_naive(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database)
    with DuckDbUnitOfWork(database) as unit_of_work:
        history = OperationHistory(unit_of_work.operations, clock=lambda: datetime(2026, 1, 2, 12))
        for operation_id, operation_type in (
            ("import", OperationType.IMPORT),
            ("validation", OperationType.VALIDATION),
            ("export", OperationType.EXPORT),
        ):
            history.start_operation(operation_id, "project", operation_type)
        history.finish_operation("import", OperationStatus.COMPLETED)
        history.finish_operation("validation", OperationStatus.CANCELLED, "CANCELLED")
        history.finish_operation("export", OperationStatus.FAILED, "EXPORT_WRITE_FAILED")
    with DuckDbUnitOfWork(database) as unit_of_work:
        items = unit_of_work.operations.list_operations("project", PageRequest()).items
    assert [item.operation_id for item in items] == ["validation", "import", "export"]
    assert all(item.started_at.tzinfo is None for item in items)
    assert items[1].finished_at == items[1].started_at


@pytest.mark.parametrize(
    ("terminal_status", "error_code"),
    (
        (OperationStatus.COMPLETED, None),
        (OperationStatus.CANCELLED, "CANCELLED"),
        (OperationStatus.FAILED, "IMPORT_FAILED"),
    ),
)
def test_file_backed_reopen_finishes_import_with_detail_in_duckdb_1_1_3(
    tmp_path: Path, terminal_status: OperationStatus, error_code: str | None
) -> None:
    """La reapertura entre UoWs protege la actualización de la PK de operations."""
    database = _database(tmp_path)
    _seed(database)

    # UoW 1: crea y confirma el detalle antes de cerrar la conexión file-backed.
    with DuckDbUnitOfWork(database) as unit_of_work:
        repository = unit_of_work.operations
        repository.start("import", "project", OperationType.IMPORT, datetime(2026, 1, 2, 12))
        repository.attach_import_detail("import", "feed", "job")

    # UoW 2: una conexión nueva reproduce el ciclo que bloqueó P1-04B1.
    with DuckDbUnitOfWork(database) as unit_of_work:
        unit_of_work.operations.finish(
            "import", terminal_status, datetime(2026, 1, 2, 13), error_code
        )

    with database.connection() as connection:
        assert connection.execute(
            "SELECT status, finished_at FROM operations WHERE operation_id = 'import'"
        ).fetchone() == (terminal_status.value, datetime(2026, 1, 2, 13))
        assert connection.execute(
            "SELECT feed_id, job_id FROM operation_import_details WHERE operation_id = 'import'"
        ).fetchone() == ("feed", "job")


def test_operations_schema_has_no_secondary_index_with_started_at(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        indexes = connection.execute(
            "SELECT expressions FROM duckdb_indexes() WHERE table_name = 'operations'"
        ).fetchall()

    assert all("started_at" not in str(index[0]).lower() for index in indexes)


def test_retained_foreign_keys_allow_real_parent_lifecycle_updates(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database)
    with DuckDbUnitOfWork(database) as unit_of_work:
        repository = unit_of_work.operations
        for operation_id, operation_type in (
            ("import", OperationType.IMPORT),
            ("validation", OperationType.VALIDATION),
            ("export", OperationType.EXPORT),
        ):
            repository.start(operation_id, "project", operation_type, datetime(2026, 1, 2, 12))
        repository.attach_import_detail("import", "feed", "job")
        repository.attach_validation_detail("validation", "feed", "batch")
        repository.attach_export_detail("export", "feed", "CSV")

    with DuckDbUnitOfWork(database) as unit_of_work:
        unit_of_work.projects.save_metadata(
            ProjectMetadata("project", "Proyecto actualizado", ProjectStatus.READY)
        )
        unit_of_work.feeds.save_metadata(
            FeedMetadata(
                "feed",
                "project",
                "feed-updated.zip",
                "1" * 64,
                "ZIP",
                "2026",
                FeedStatus.IMPORTED,
            )
        )
        unit_of_work.import_jobs.save_metadata(
            ImportJobMetadata("job", "feed", JobState.SUCCEEDED, "DONE", 1)
        )

    with database.connection() as connection:
        connection.execute(
            "UPDATE validation_runs SET status = 'VALID', total_issue_count = 0, "
            "stored_issue_count = 0, omitted_issue_count = 0 WHERE batch_id = 'batch'"
        )
        assert connection.execute(
            "SELECT p.name, f.source_name, j.state, v.status "
            "FROM projects p, feeds f, import_jobs j, validation_runs v "
            "WHERE p.project_id = 'project' AND f.feed_id = 'feed' "
            "AND j.job_id = 'job' AND v.batch_id = 'batch'"
        ).fetchone() == ("Proyecto actualizado", "feed-updated.zip", "SUCCEEDED", "VALID")


def test_logical_operation_reference_is_enforced_by_repository(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database)
    with DuckDbUnitOfWork(database) as unit_of_work:
        with pytest.raises(ValueError, match="La operación no existe"):
            unit_of_work.operations.attach_export_detail("missing", "feed", "CSV")


@pytest.mark.parametrize("missing_reference", ("project", "operation", "feed", "job", "batch"))
def test_references_that_do_not_exist_are_rejected(tmp_path: Path, missing_reference: str) -> None:
    database = _database(tmp_path)
    _seed(database)
    with DuckDbUnitOfWork(database) as unit_of_work:
        repository = unit_of_work.operations
        now = datetime(2026, 1, 2)
        if missing_reference == "project":
            with pytest.raises(duckdb.ConstraintException):
                repository.start("operation", "missing", OperationType.IMPORT, now)
        elif missing_reference == "operation":
            with pytest.raises(ValueError, match="La operación no existe"):
                repository.attach_export_detail("missing", "feed", "CSV")
        elif missing_reference == "feed":
            repository.start("operation", "project", OperationType.IMPORT, now)
            with pytest.raises(duckdb.ConstraintException):
                repository.attach_import_detail("operation", "missing", "job")
        elif missing_reference == "job":
            repository.start("operation", "project", OperationType.IMPORT, now)
            with pytest.raises(duckdb.ConstraintException):
                repository.attach_import_detail("operation", "feed", "missing")
        else:
            repository.start("operation", "project", OperationType.VALIDATION, now)
            with pytest.raises(duckdb.ConstraintException):
                repository.attach_validation_detail("operation", "feed", "missing")


def test_schema_keeps_safe_foreign_keys_and_one_to_one_constraints(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT table_name, constraint_type, constraint_column_names, referenced_table, "
            "referenced_column_names FROM duckdb_constraints() "
            "WHERE table_name IN ('operations', 'operation_import_details', "
            "'operation_validation_details', 'operation_export_details')"
        ).fetchall()

    foreign_keys = {
        (str(row[0]), tuple(row[2]), str(row[3]), tuple(row[4]))
        for row in rows
        if row[1] == "FOREIGN KEY"
    }
    assert foreign_keys == {
        ("operations", ("project_id",), "projects", ("project_id",)),
        ("operation_import_details", ("feed_id",), "feeds", ("feed_id",)),
        ("operation_import_details", ("job_id",), "import_jobs", ("job_id",)),
        ("operation_validation_details", ("feed_id",), "feeds", ("feed_id",)),
        (
            "operation_validation_details",
            ("validation_batch_id",),
            "validation_runs",
            ("batch_id",),
        ),
        ("operation_export_details", ("feed_id",), "feeds", ("feed_id",)),
    }
    keyed_columns = {
        (str(row[0]), str(row[1]), tuple(row[2]))
        for row in rows
        if row[1] in ("PRIMARY KEY", "UNIQUE")
    }
    assert keyed_columns == {
        ("operations", "PRIMARY KEY", ("operation_id",)),
        ("operation_import_details", "PRIMARY KEY", ("operation_id",)),
        ("operation_import_details", "UNIQUE", ("job_id",)),
        ("operation_validation_details", "PRIMARY KEY", ("operation_id",)),
        ("operation_validation_details", "UNIQUE", ("validation_batch_id",)),
        ("operation_export_details", "PRIMARY KEY", ("operation_id",)),
    }


def test_details_invariants_hash_normalization_and_validation_join(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database)
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO validation_runs VALUES ('job:structure', 'feed', 'INVALID', 3, 3, 0)"
        )
    with DuckDbUnitOfWork(database) as unit_of_work:
        repository = unit_of_work.operations
        now = datetime(2026, 1, 2)
        repository.start("import", "project", OperationType.IMPORT, now)
        repository.start("validation", "project", OperationType.VALIDATION, now)
        repository.start("export", "project", OperationType.EXPORT, now)
        repository.attach_import_detail("import", "feed", "job")
        repository.attach_validation_detail("validation", "feed", "batch")
        repository.attach_export_detail("export", "feed", "CSV", "report.csv", "A" * 64, 10)
        repository.start("other-import", "project", OperationType.IMPORT, now)
        repository.start("other-validation", "project", OperationType.VALIDATION, now)
        with pytest.raises(Exception):
            repository.attach_import_detail("import", "feed", "job")
        with pytest.raises(ValueError):
            repository.attach_import_detail("other-import", "feed", "job")
        with pytest.raises(Exception):
            repository.attach_validation_detail("import", "feed", None)
        with pytest.raises(Exception):
            repository.attach_validation_detail("validation", "feed", "batch")
        with pytest.raises(ValueError):
            repository.attach_validation_detail("other-validation", "feed", "batch")
    with DuckDbUnitOfWork(database) as unit_of_work:
        entries = {
            item.operation_id: item
            for item in unit_of_work.operations.list_operations("project", PageRequest()).items
        }
    assert entries["validation"].validation_result == "INVALID"
    assert entries["validation"].validation_issue_count == 3
    assert entries["import"].validation_batch_id == "job:structure"
    assert entries["import"].validation_result == "INVALID"
    assert entries["import"].validation_issue_count == 3
    assert entries["export"].artifact_sha256 == "a" * 64


def test_import_validation_projection_uses_validation_run_aggregates_only(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database)
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO validation_runs VALUES ('job:structure', 'feed', 'INVALID', 3, 3, 0)"
        )
    with DuckDbUnitOfWork(database) as unit_of_work:
        repository = unit_of_work.operations
        repository.start("import", "project", OperationType.IMPORT, datetime(2026, 1, 2))
        repository.attach_import_detail("import", "feed", "job")
        item = repository.list_operations("project", PageRequest()).items[0]

    assert item.validation_result == "INVALID"
    assert item.validation_issue_count == 3


@pytest.mark.parametrize(
    "artifact_name", ["C:\\secret\\report.csv", "/secret/report.csv", "dir/report.csv"]
)
def test_export_rejects_paths_and_invalid_hash(tmp_path: Path, artifact_name: str) -> None:
    database = _database(tmp_path)
    _seed(database)
    with DuckDbUnitOfWork(database) as unit_of_work:
        repository = unit_of_work.operations
        repository.start("export", "project", OperationType.EXPORT, datetime(2026, 1, 2))
        with pytest.raises(ValueError):
            repository.attach_export_detail("export", "feed", "CSV", artifact_name, "0" * 64, 1)
        with pytest.raises(ValueError):
            repository.attach_export_detail("export", "feed", "CSV", "report.csv", "bad", 1)


@pytest.mark.parametrize(
    "error_code", ["traceback: C:\\Users\\secret", "password=secret", "lowercase"]
)
def test_error_codes_are_stable_and_transitions_are_one_way(
    tmp_path: Path, error_code: str
) -> None:
    database = _database(tmp_path)
    _seed(database)
    with DuckDbUnitOfWork(database) as unit_of_work:
        repository = unit_of_work.operations
        repository.start("operation", "project", OperationType.EXPORT, datetime(2026, 1, 2, 12))
        with pytest.raises(ValueError):
            repository.finish(
                "operation", OperationStatus.FAILED, datetime(2026, 1, 2, 13), error_code
            )
        with pytest.raises(ValueError):
            repository.finish("operation", OperationStatus.COMPLETED, datetime(2026, 1, 2, 11))
        repository.finish("operation", OperationStatus.COMPLETED, datetime(2026, 1, 2, 13))
        with pytest.raises(ValueError):
            repository.finish(
                "operation", OperationStatus.FAILED, datetime(2026, 1, 2, 14), "FAILED"
            )


def test_listing_filters_order_and_interrupted_is_derived_without_mutation(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database)
    with DuckDbUnitOfWork(database) as unit_of_work:
        repository = unit_of_work.operations
        repository.start("a", "project", OperationType.IMPORT, datetime(2026, 1, 2))
        repository.start("b", "project", OperationType.EXPORT, datetime(2026, 1, 3))
        repository.start("c", "project", OperationType.EXPORT, datetime(2026, 1, 3))
        repository.finish("b", OperationStatus.COMPLETED, datetime(2026, 1, 4))
        exports = repository.list_operations("project", PageRequest(), OperationType.EXPORT)
        running = repository.list_operations(
            "project", PageRequest(), status=OperationStatus.RUNNING
        )
        assert [item.operation_id for item in exports.items] == ["c", "b"]
        assert [item.operation_id for item in running.items] == ["c", "a"]
        assert display_status(running.items[0], frozenset()) is OperationDisplayStatus.INTERRUPTED
        assert display_status(running.items[0], frozenset({"c"})) is OperationDisplayStatus.RUNNING
    with database.connection() as connection:
        assert connection.execute(
            "SELECT status FROM operations WHERE operation_id = 'c'"
        ).fetchone() == ("RUNNING",)
