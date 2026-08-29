"""Operaciones confinadas para recuperar temporales de un workspace."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

import duckdb

from gtfs_explorer.domain.project import FeedMetadata, FeedStatus, ProjectMetadata, ProjectStatus
from gtfs_explorer.infrastructure.duckdb.database import (
    DatabaseSettings,
    ProjectDatabase,
)
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    ProjectDescriptorError,
    ProjectDescriptorReconciliation,
    classify_project_descriptor,
    load_project_descriptor,
    save_project_descriptor,
)


@dataclass(frozen=True)
class WorkspaceAction:
    """Una acción de cuarentena o limpieza con su objetivo absoluto exacto."""

    kind: str
    target: Path


class RecoveryState(StrEnum):
    """Clasificación no persistida del estado de un workspace."""

    HEALTHY = "HEALTHY"
    RECOVERABLE_DESCRIPTOR = "RECOVERABLE_DESCRIPTOR"
    RECOVERABLE_TRANSIENT = "RECOVERABLE_TRANSIENT"
    RESTORE_CANDIDATE_AVAILABLE = "RESTORE_CANDIDATE_AVAILABLE"
    CANONICAL_DATABASE_UNAVAILABLE = "CANONICAL_DATABASE_UNAVAILABLE"
    UNRECOVERABLE = "UNRECOVERABLE"


@dataclass(frozen=True)
class DatabaseInspection:
    """Resultado seguro de abrir y consultar una DuckDB sin migrarla."""

    path: Path
    exists: bool
    opens: bool
    schema_version: int | None
    supported: bool
    project: ProjectMetadata | None
    feed: FeedMetadata | None
    reason_code: str | None = None


@dataclass(frozen=True)
class BackupCandidate:
    """Candidato inventariado y validado, sin exponer su ruta en la UI."""

    path: Path
    name: str
    modified_at: str
    size_bytes: int
    valid: bool
    schema_version: int | None
    project_id: str | None
    reason_code: str | None = None


@dataclass(frozen=True)
class RecoveryInspection:
    """Diagnóstico previo a cualquier reparación o restauración."""

    workspace: Path
    state: str
    database: DatabaseInspection
    descriptor_kind: str
    expected_descriptor: ProjectDescriptor | None
    lock_state: str
    transient_candidates: tuple[Path, ...]
    backup_candidates: tuple[BackupCandidate, ...]


class RecoveryError(RuntimeError):
    """Error seguro de una operación explícita de recuperación."""


class RecoveryCandidateAvailableError(RecoveryError):
    """La base actual no abre y existe una copia validada para ofrecer al usuario."""

    def __init__(self, inspection: RecoveryInspection) -> None:
        super().__init__("La base actual no puede abrirse. Hay una copia recuperable.")
        self.inspection = inspection


class RecoveryUnavailableError(RecoveryError):
    """El workspace no puede recuperarse sin destruir o inventar datos."""


_MIGRATION_PATTERN = re.compile(r"^(\d+)_.*\.sql$")
_CURRENT_MIGRATION_VERSION = max(
    int(match.group(1))
    for path in (Path(__file__).parents[1] / "duckdb" / "migrations").glob("*.sql")
    if (match := _MIGRATION_PATTERN.match(path.name))
)
_CURRENT_REQUIRED_TABLES = frozenset(
    {
        "schema_migrations",
        "schema_metadata",
        "stg_source_inventory",
        "normalization_issues",
        "gtfs_agency",
        "gtfs_stops",
        "gtfs_routes",
        "gtfs_trips",
        "gtfs_stop_times",
        "gtfs_calendar",
        "gtfs_calendar_dates",
        "gtfs_shapes",
        "gtfs_frequencies",
        "gtfs_transfers",
        "gtfs_feed_info",
        "gtfs_attributions",
        "projects",
        "feeds",
        "import_jobs",
        "validation_runs",
        "validation_issues",
        "operations",
        "operation_import_details",
        "operation_validation_details",
        "operation_export_details",
    }
)
_MINIMUM_RESTORABLE_TABLES = frozenset(
    {"schema_migrations", "schema_metadata", "projects", "feeds", "import_jobs"}
)


def inspect_database(path: Path, *, candidate: bool = False) -> DatabaseInspection:
    """Abre una copia file-backed y ejecuta consultas mínimas, sin migrar ni reparar."""

    if not path.is_file():
        return DatabaseInspection(path, False, False, None, False, None, None, "MISSING")
    try:
        connection = duckdb.connect(str(path), read_only=True)
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
            }
            if "schema_metadata" not in tables or "schema_migrations" not in tables:
                return DatabaseInspection(path, True, True, None, False, None, None, "SCHEMA")
            schema_row = connection.execute("SELECT schema_version FROM schema_metadata").fetchone()
            migration_row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()
            if (
                schema_row is None
                or migration_row is None
                or not isinstance(schema_row[0], int)
                or schema_row[0] != migration_row[0]
            ):
                return DatabaseInspection(path, True, True, None, False, None, None, "SCHEMA")
            version = int(schema_row[0])
            required = _MINIMUM_RESTORABLE_TABLES if candidate else _CURRENT_REQUIRED_TABLES
            if not required.issubset(tables) or not 1 <= version <= _CURRENT_MIGRATION_VERSION:
                return DatabaseInspection(path, True, True, version, False, None, None, "SCHEMA")
            project_rows = connection.execute(
                "SELECT project_id, name, status FROM projects ORDER BY created_at"
            ).fetchall()
            if len(project_rows) != 1:
                return DatabaseInspection(path, True, True, version, False, None, None, "IDENTITY")
            try:
                project = ProjectMetadata(
                    str(project_rows[0][0]),
                    str(project_rows[0][1]),
                    ProjectStatus(project_rows[0][2]),
                )
                feed_row = connection.execute(
                    "SELECT feed_id, project_id, source_name, source_sha256, import_mode, "
                    "spec_revision, status FROM feeds ORDER BY imported_at DESC LIMIT 1"
                ).fetchone()
                feed = None
                if feed_row is not None:
                    feed = FeedMetadata(
                        str(feed_row[0]),
                        str(feed_row[1]),
                        str(feed_row[2]),
                        str(feed_row[3]),
                        str(feed_row[4]),
                        str(feed_row[5]),
                        FeedStatus(feed_row[6]),
                    )
                # Estas consultas son deliberadamente pequeñas y ejercitan el contrato canónico.
                connection.execute("SELECT count(*) FROM projects").fetchone()
                connection.execute("SELECT count(*) FROM feeds").fetchone()
                connection.execute("SELECT count(*) FROM import_jobs").fetchone()
            except (ValueError, TypeError, duckdb.Error):
                return DatabaseInspection(path, True, True, version, False, None, None, "SEMANTIC")
            return DatabaseInspection(path, True, True, version, True, project, feed)
        finally:
            connection.close()
    except duckdb.Error:
        return DatabaseInspection(path, True, False, None, False, None, None, "UNAVAILABLE")


def inspect_recovery_state(workspace: Path, *, lock_state: str = "NOT_HELD") -> RecoveryInspection:
    """Diagnostica DB, descriptor, lock, temporales y backups antes de mutar."""

    root = workspace.resolve()
    database_path = root / "data.duckdb"
    database = inspect_database(database_path)
    expected = None
    descriptor_kind = "NOT_EVALUATED"
    if database.opens and database.supported and database.project is not None:
        expected = ProjectDescriptor.from_metadata(database.project, database.feed, root)
        descriptor_path = root / "project.json"
        if not descriptor_path.exists():
            descriptor_kind = "MISSING"
        else:
            try:
                actual = load_project_descriptor(descriptor_path)
            except ProjectDescriptorError:
                descriptor_kind = "INVALID"
            else:
                reconciliation = classify_project_descriptor(actual, expected)
                descriptor_kind = {
                    ProjectDescriptorReconciliation.MATCH: "MATCH",
                    ProjectDescriptorReconciliation.RECOVERABLE_LEGACY_MISMATCH: (
                        "RECOVERABLE_MISMATCH"
                    ),
                    ProjectDescriptorReconciliation.UNRECOVERABLE_MISMATCH: (
                        "UNRECOVERABLE_MISMATCH"
                    ),
                }[reconciliation]
    transient = tuple(_transient_candidates(root / "temp"))
    expected_project_id = (
        database.project.project_id if database.project else _descriptor_project_id(root)
    )
    candidates = _inventory_backup_candidates(root, expected_project_id)
    if database.opens and database.supported:
        if descriptor_kind in {"MISSING", "INVALID", "RECOVERABLE_MISMATCH"}:
            state = RecoveryState.RECOVERABLE_DESCRIPTOR
        elif descriptor_kind == "UNRECOVERABLE_MISMATCH":
            state = RecoveryState.UNRECOVERABLE
        elif transient:
            state = RecoveryState.RECOVERABLE_TRANSIENT
        else:
            state = RecoveryState.HEALTHY
    elif any(candidate.valid for candidate in candidates):
        state = RecoveryState.RESTORE_CANDIDATE_AVAILABLE
    else:
        state = RecoveryState.UNRECOVERABLE
    return RecoveryInspection(
        root, state, database, descriptor_kind, expected, lock_state, transient, candidates
    )


def rebuild_descriptor_from_canonical(
    workspace: Path, *, snapshot_existing: bool = True
) -> ProjectDescriptor:
    """Reconstruye project.json exclusivamente desde una DB ya inspeccionada como válida."""

    inspection = inspect_recovery_state(workspace, lock_state="HELD")
    if not inspection.database.supported or inspection.expected_descriptor is None:
        raise RecoveryUnavailableError("La base canónica no permite reconstruir el descriptor.")
    descriptor_path = inspection.workspace / "project.json"
    if snapshot_existing and descriptor_path.exists():
        snapshot = create_recovery_snapshot(inspection.workspace, include_database=False)
        _write_recovery_report(snapshot, inspection, ("DESCRIPTOR_SNAPSHOT",), "STAGED")
    save_project_descriptor(descriptor_path, inspection.expected_descriptor)
    verified = load_project_descriptor(descriptor_path)
    if verified.to_dict() != inspection.expected_descriptor.to_dict():
        raise RecoveryError("El descriptor reconstruido no se pudo verificar.")
    return verified


def create_recovery_snapshot(workspace: Path, *, include_database: bool) -> Path:
    """Preserva los originales antes de sustituir archivos importantes."""

    root = workspace.resolve()
    recovery_root = root / "recovery" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    recovery_root = recovery_root.with_name(f"{recovery_root.name}-{uuid4().hex[:8]}")
    recovery_root.mkdir(parents=True, exist_ok=False)
    if include_database:
        database = root / "data.duckdb"
        if not database.is_file():
            raise RecoveryError("No se puede preservar la base canónica original.")
        shutil.copy2(database, recovery_root / "original.duckdb")
    descriptor = root / "project.json"
    if descriptor.is_file():
        shutil.copy2(descriptor, recovery_root / "project.json")
    return recovery_root


def restore_backup(workspace: Path, candidate: BackupCandidate) -> Path:
    """Restaura explícitamente un candidato validado mediante staging y publicación segura."""

    from gtfs_explorer.application.commands.open_project import ProjectWriterLock

    root = workspace.resolve()
    known_candidates = {
        item.path.resolve()
        for item in _inventory_backup_candidates(root, _descriptor_project_id(root))
    }
    if candidate.path.resolve() not in known_candidates:
        raise RecoveryUnavailableError("La copia seleccionada ya no es un candidato del proyecto.")
    writer_lock = ProjectWriterLock(root)
    writer_lock.acquire()
    try:
        inspection = inspect_recovery_state(root, lock_state="HELD")
        selected = next(
            (
                item
                for item in inspection.backup_candidates
                if item.path.resolve() == candidate.path.resolve()
            ),
            None,
        )
        if selected is None or not selected.valid:
            raise RecoveryUnavailableError("La copia seleccionada no supera la validación actual.")
        if inspection.state != RecoveryState.RESTORE_CANDIDATE_AVAILABLE:
            raise RecoveryUnavailableError("El proyecto ya no está en un estado restaurable.")
        try:
            snapshot = create_recovery_snapshot(root, include_database=True)
        except Exception as error:
            raise RecoveryError(
                "No se pudo preservar el original; no se ha iniciado la restauración."
            ) from error
        try:
            staging = snapshot / "staging"
            staging.mkdir()
            staged_database = staging / "data.duckdb"
            shutil.copy2(selected.path, staged_database)
            staged_db = ProjectDatabase(
                staged_database,
                staging / "temp",
                settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
            )
            staged_db.initialize()
            staged_db.validate_compatible()
            staged_inspection = inspect_database(staged_database)
            if not staged_inspection.supported or staged_inspection.project is None:
                raise RecoveryUnavailableError("La copia no se pudo validar tras la preparación.")
            expected_id = _descriptor_project_id(root)
            if expected_id is None or staged_inspection.project.project_id != expected_id:
                raise RecoveryUnavailableError(
                    "La copia no pertenece inequívocamente a este proyecto."
                )
            staged_descriptor = ProjectDescriptor.from_metadata(
                staged_inspection.project, staged_inspection.feed, root
            )
            # La UoW comprueba que la base preparada permite el flujo normal de apertura.
            from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork

            with DuckDbUnitOfWork(staged_db) as unit_of_work:
                if unit_of_work.projects.metadata() is None:
                    raise RecoveryUnavailableError(
                        "La copia no contiene metadatos canónicos completos."
                    )
                unit_of_work.overview.overview()
        except RecoveryUnavailableError:
            raise
        except Exception as error:
            raise RecoveryError(
                "La copia no se pudo preparar; el original permanece intacto."
            ) from error
        try:
            os.replace(staged_database, root / "data.duckdb")
        except OSError as error:
            raise RecoveryError(
                "La publicación de la recuperación no se ha completado; el original permanece."
            ) from error
        try:
            save_project_descriptor(root / "project.json", staged_descriptor)
        except Exception as error:
            _rollback_snapshot(root, snapshot)
            raise RecoveryError(
                "La publicación de la recuperación ha fallado y se ha revertido."
            ) from error
        _write_recovery_report(
            snapshot, inspection, ("SNAPSHOT_CREATED", "STAGED_VALIDATED", "PUBLISHED"), "RESTORED"
        )
        return snapshot
    finally:
        writer_lock.release()


def _rollback_snapshot(root: Path, snapshot: Path) -> None:
    original = snapshot / "original.duckdb"
    if original.is_file():
        shutil.copy2(original, root / "data.duckdb")
    original_descriptor = snapshot / "project.json"
    target_descriptor = root / "project.json"
    if original_descriptor.is_file():
        shutil.copy2(original_descriptor, target_descriptor)


def _write_recovery_report(
    snapshot: Path, inspection: RecoveryInspection, actions: tuple[str, ...], result: str
) -> None:
    payload = {
        "recovery_id": snapshot.name,
        "detected_state": inspection.state,
        "actions": list(actions),
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (snapshot / "recovery-report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _descriptor_project_id(root: Path) -> str | None:
    try:
        return load_project_descriptor(root / "project.json").project_id
    except (OSError, ProjectDescriptorError):
        return None


def _transient_candidates(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        candidate
        for candidate in directory.iterdir()
        if candidate.is_dir()
        and (candidate.name.startswith("import-") or candidate.name.endswith(".staging"))
    )


def _inventory_backup_candidates(
    root: Path, expected_project_id: str | None
) -> tuple[BackupCandidate, ...]:
    paths = [root / "data.duckdb.pre-migration.bak", root / "data.duckdb.bak"]
    paths.extend(sorted(root.glob("data.duckdb.*.bak")))
    result: list[BackupCandidate] = []
    for path in dict.fromkeys(paths):
        if not path.is_file():
            continue
        inspection = inspect_database(path, candidate=True)
        valid = inspection.supported and inspection.project is not None
        reason = inspection.reason_code
        if valid and expected_project_id is None:
            valid = False
            reason = "NO_CANONICAL_IDENTITY"
        elif valid and inspection.project and inspection.project.project_id != expected_project_id:
            valid = False
            reason = "IDENTITY_MISMATCH"
        try:
            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            size = stat.st_size
        except OSError:
            modified = ""
            size = 0
        result.append(
            BackupCandidate(
                path,
                path.name,
                modified,
                size,
                valid,
                inspection.schema_version,
                inspection.project.project_id if inspection.project else None,
                reason,
            )
        )
    return tuple(result)


class WorkspaceRecovery:
    """Mueve temporales huérfanos a cuarentena y los borra solo bajo confirmación."""

    def __init__(self, temporary_directory: Path) -> None:
        self._temporary_directory = temporary_directory
        self._quarantine_directory = temporary_directory / "quarantine"

    def quarantine_import_temporary_directories(self) -> tuple[WorkspaceAction, ...]:
        """Aísla directorios ``import-*`` que pertenecen al temporal del proyecto."""
        if not self._temporary_directory.is_dir():
            return ()
        actions: list[WorkspaceAction] = []
        for candidate in self._temporary_directory.glob("import-*"):
            target = self._verified_child(candidate, self._temporary_directory)
            if target is None or not target.is_dir():
                continue
            self._quarantine_directory.mkdir(parents=True, exist_ok=True)
            destination = self._quarantine_directory / f"{target.name}-{uuid4().hex}"
            target.rename(destination)
            actions.append(WorkspaceAction("QUARANTINED", destination.resolve()))
        return tuple(actions)

    def cleanup_quarantine(self, *, confirmed: bool) -> tuple[WorkspaceAction, ...]:
        """Elimina cuarentenas verificadas únicamente tras confirmación del llamador."""
        if not confirmed or not self._quarantine_directory.is_dir():
            return ()
        actions: list[WorkspaceAction] = []
        for candidate in self._quarantine_directory.iterdir():
            target = self._verified_child(candidate, self._quarantine_directory)
            if target is None or not target.is_dir():
                continue
            shutil.rmtree(target)
            actions.append(WorkspaceAction("DELETED", target))
        return tuple(actions)

    @staticmethod
    def _verified_child(candidate: Path, parent: Path) -> Path | None:
        """Acepta solo hijos reales del directorio controlado, nunca enlaces que escapen."""
        resolved_parent = parent.resolve()
        try:
            resolved_candidate = candidate.resolve()
            resolved_candidate.relative_to(resolved_parent)
        except (OSError, ValueError):
            return None
        if resolved_candidate.parent != resolved_parent:
            return None
        return resolved_candidate
