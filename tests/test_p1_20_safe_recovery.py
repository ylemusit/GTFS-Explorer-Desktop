"""Regresión file-backed de P1-20: inspección, preservación y restauración segura."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from gtfs_explorer.application.commands.open_project import OpenProject
from gtfs_explorer.application.commands.recover_workspace import RestoreWorkspace
from gtfs_explorer.domain.operations import OperationDisplayStatus, OperationType, display_status
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.domain.project import FeedMetadata, FeedStatus, ProjectMetadata, ProjectStatus
from gtfs_explorer.infrastructure.duckdb.database import (
    DatabaseCorruptionError,
    DatabaseSettings,
    ProjectDatabase,
)
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    ProjectDescriptorUnrecoverableMismatchError,
    save_project_descriptor,
)
from gtfs_explorer.infrastructure.filesystem.workspace_recovery import (
    RecoveryError,
    RecoveryState,
    inspect_recovery_state,
)


def _database(project: Path) -> ProjectDatabase:
    return ProjectDatabase(
        project / "data.duckdb",
        project / "temp",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )


def _seed(project: Path, project_id: str = "project-1", feed: bool = True) -> None:
    database = _database(project)
    with DuckDbUnitOfWork(database) as unit_of_work:
        metadata = ProjectMetadata(project_id, "Proyecto de prueba", ProjectStatus.READY)
        unit_of_work.projects.save_metadata(metadata)
        if feed:
            unit_of_work.feeds.save_metadata(
                FeedMetadata(
                    "feed-1",
                    project_id,
                    "feed.zip",
                    "a" * 64,
                    "strict",
                    "2026-04-27",
                    FeedStatus.IMPORTED,
                )
            )
    with DuckDbUnitOfWork(database) as unit_of_work:
        save_project_descriptor(
            project / "project.json",
            ProjectDescriptor.from_metadata(
                unit_of_work.projects.metadata(), unit_of_work.feeds.latest_metadata(), project
            ),
        )


def _make_backup(project: Path, source: Path | None = None) -> Path:
    backup = project / "data.duckdb.pre-migration.bak"
    shutil.copy2(source or project / "data.duckdb", backup)
    return backup


def test_inspection_classifies_healthy_and_never_writes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _seed(project)
    before = {path.name: path.read_bytes() for path in project.iterdir() if path.is_file()}

    inspection = inspect_recovery_state(project)

    assert inspection.state == RecoveryState.HEALTHY
    assert inspection.database.project is not None
    assert inspection.database.project.project_id == "project-1"
    assert inspection.descriptor_kind == "MATCH"
    assert {path.name: path.read_bytes() for path in project.iterdir() if path.is_file()} == before


def test_public_inspection_observes_active_os_lock_without_mutating_sentinel(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _seed(project)

    with OpenProject(project).execute():
        inspection = RestoreWorkspace(project).inspect()

    assert inspection.lock_state == "ACTIVE"
    assert not (project / ".writer.lock").exists()


@pytest.mark.parametrize("payload", [b"{", b"not-json"])
def test_invalid_or_truncated_descriptor_rebuilds_from_canonical_with_snapshot(
    tmp_path: Path, payload: bytes
) -> None:
    project = tmp_path / "project"
    _seed(project)
    descriptor = project / "project.json"
    descriptor.write_bytes(payload)

    inspection = inspect_recovery_state(project)
    assert inspection.state == RecoveryState.RECOVERABLE_DESCRIPTOR
    OpenProject(project).execute().close()

    assert json.loads(descriptor.read_text(encoding="utf-8"))["project_id"] == "project-1"
    snapshots = list((project / "recovery").iterdir())
    assert len(snapshots) == 1
    assert (snapshots[0] / "project.json").read_bytes() == payload
    report = json.loads((snapshots[0] / "recovery-report.json").read_text(encoding="utf-8"))
    assert set(report) == {"recovery_id", "detected_state", "actions", "result", "timestamp"}


def test_recoverable_legacy_mismatch_reuses_p0_001_and_reopen_works(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _seed(project)
    payload = json.loads((project / "project.json").read_text(encoding="utf-8"))
    payload["feed"] = None
    (project / "project.json").write_text(json.dumps(payload), encoding="utf-8")

    assert inspect_recovery_state(project).state == RecoveryState.RECOVERABLE_DESCRIPTOR
    with OpenProject(project).execute():
        pass
    with OpenProject(project).execute() as opened:
        with DuckDbUnitOfWork(opened.database) as unit_of_work:
            assert unit_of_work.feeds.latest_metadata() is not None
    assert (
        json.loads((project / "project.json").read_text(encoding="utf-8"))["feed"]["feed_id"]
        == "feed-1"
    )


def test_missing_descriptor_is_recoverable_without_using_it_as_database_source(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _seed(project)
    (project / "project.json").unlink()

    assert inspect_recovery_state(project).descriptor_kind == "MISSING"
    with OpenProject(project).execute() as opened:
        assert opened.descriptor.project_id == "project-1"
    assert (
        json.loads((project / "project.json").read_text(encoding="utf-8"))["project_id"]
        == "project-1"
    )


def test_running_operation_remains_running_and_is_only_displayed_as_interrupted(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _seed(project)
    with DuckDbUnitOfWork(_database(project)) as unit_of_work:
        unit_of_work.operations.start(
            "op-1", "project-1", OperationType.IMPORT, datetime(2026, 1, 1)
        )

    with OpenProject(project).execute():
        pass
    with DuckDbUnitOfWork(_database(project)) as unit_of_work:
        operation = unit_of_work.operations.list_operations("project-1", PageRequest()).items[0]

    assert operation.status.value == "RUNNING"
    assert display_status(operation, frozenset()) is OperationDisplayStatus.INTERRUPTED


def test_nonrecoverable_identity_mismatch_does_not_mutate(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _seed(project)
    descriptor = project / "project.json"
    payload = json.loads(descriptor.read_text(encoding="utf-8"))
    payload["project_id"] = "other-project"
    descriptor.write_text(json.dumps(payload), encoding="utf-8")
    before = descriptor.read_bytes()

    inspection = inspect_recovery_state(project)

    assert inspection.state == RecoveryState.UNRECOVERABLE
    with pytest.raises(ProjectDescriptorUnrecoverableMismatchError):
        OpenProject(project).execute()
    assert descriptor.read_bytes() == before


def test_stale_transient_is_recoverable_and_quarantined_without_db_repair(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _seed(project)
    transient = project / "temp" / "import-crashed"
    transient.mkdir(parents=True)
    (transient / "partial.part").write_text("incomplete", encoding="utf-8")

    inspection = inspect_recovery_state(project)
    assert inspection.state == RecoveryState.RECOVERABLE_TRANSIENT
    with OpenProject(project).execute():
        pass

    assert not transient.exists()
    quarantined = list((project / "temp" / "quarantine").iterdir())
    assert len(quarantined) == 1
    assert (quarantined[0] / "partial.part").read_text(encoding="utf-8") == "incomplete"


def test_corrupt_database_without_valid_backup_is_unrecoverable_and_preserved(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _seed(project)
    database = project / "data.duckdb"
    database.write_bytes(b"corrupt-canonical")
    before = database.read_bytes()

    inspection = inspect_recovery_state(project)

    assert inspection.state == RecoveryState.UNRECOVERABLE
    with pytest.raises(DatabaseCorruptionError):
        OpenProject(project).execute()
    assert database.read_bytes() == before


def test_valid_backup_is_explicitly_restored_in_staging_and_reopens(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _seed(project)
    backup = _make_backup(project)
    database = project / "data.duckdb"
    database.write_bytes(b"corrupt-canonical")
    original = database.read_bytes()

    inspection = inspect_recovery_state(project)
    assert inspection.state == RecoveryState.RESTORE_CANDIDATE_AVAILABLE
    candidate = next(item for item in inspection.backup_candidates if item.valid)
    snapshot = RestoreWorkspace(project).execute(candidate)

    assert database.read_bytes() != original
    assert (snapshot / "original.duckdb").read_bytes() == original
    assert backup.exists()
    report = json.loads((snapshot / "recovery-report.json").read_text(encoding="utf-8"))
    assert report["result"] == "RESTORED"
    with OpenProject(project).execute() as opened:
        assert opened.descriptor.project_id == "project-1"
        with DuckDbUnitOfWork(opened.database) as unit_of_work:
            assert unit_of_work.feeds.latest_metadata() is not None


def test_invalid_backup_is_not_offered(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _seed(project)
    (project / "data.duckdb.pre-migration.bak").write_bytes(b"not-a-db")
    (project / "data.duckdb").write_bytes(b"not-a-db")

    inspection = inspect_recovery_state(project)

    assert inspection.state == RecoveryState.UNRECOVERABLE
    assert len(inspection.backup_candidates) == 1
    assert not inspection.backup_candidates[0].valid


def test_recovery_inspection_cancelled_leaves_everything_unchanged(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _seed(project)
    _make_backup(project)
    database = project / "data.duckdb"
    database.write_bytes(b"not-a-db")
    before = {path.name: path.read_bytes() for path in project.iterdir() if path.is_file()}

    inspection = RestoreWorkspace(project).inspect()
    assert inspection.state == RecoveryState.RESTORE_CANDIDATE_AVAILABLE
    # La cancelación equivale a no ejecutar el candidato ofrecido.
    assert {path.name: path.read_bytes() for path in project.iterdir() if path.is_file()} == before


def test_backup_from_another_project_is_rejected_by_canonical_identity(tmp_path: Path) -> None:
    project = tmp_path / "project"
    other = tmp_path / "other"
    _seed(project, "project-1")
    _seed(other, "project-2")
    shutil.copy2(other / "data.duckdb", project / "data.duckdb.pre-migration.bak")
    (project / "data.duckdb").write_bytes(b"not-a-db")

    inspection = inspect_recovery_state(project)

    assert inspection.state == RecoveryState.UNRECOVERABLE
    assert inspection.backup_candidates[0].reason_code == "IDENTITY_MISMATCH"


def test_failure_during_staging_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    _seed(project)
    _make_backup(project)
    database = project / "data.duckdb"
    database.write_bytes(b"corrupt-canonical")
    before = database.read_bytes()
    original_copy2 = shutil.copy2

    def fail_only_staged(
        source: str | Path, destination: str | Path, *args: object, **kwargs: object
    ):
        if Path(destination).parent.name == "staging":
            raise OSError("injected staging failure")
        return original_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr(
        "gtfs_explorer.infrastructure.filesystem.workspace_recovery.shutil.copy2",
        fail_only_staged,
    )
    candidate = next(
        item for item in inspect_recovery_state(project).backup_candidates if item.valid
    )

    with pytest.raises(RecoveryError, match="original permanece intacto"):
        RestoreWorkspace(project).execute(candidate)
    assert database.read_bytes() == before


def test_failure_before_publish_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    _seed(project)
    _make_backup(project)
    database = project / "data.duckdb"
    database.write_bytes(b"corrupt-canonical")
    before = database.read_bytes()
    original_replace = __import__("os").replace

    def fail_publish(source: str | Path, destination: str | Path):
        if Path(source).parent.name == "staging":
            raise OSError("injected publish failure")
        return original_replace(source, destination)

    monkeypatch.setattr(
        "gtfs_explorer.infrastructure.filesystem.workspace_recovery.os.replace", fail_publish
    )
    candidate = next(
        item for item in inspect_recovery_state(project).backup_candidates if item.valid
    )

    with pytest.raises(RecoveryError, match="original permanece"):
        RestoreWorkspace(project).execute(candidate)
    assert database.read_bytes() == before
