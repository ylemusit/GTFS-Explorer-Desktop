"""Recupera trabajos interrumpidos al abrir un proyecto."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gtfs_explorer.domain.project import ProjectMetadata, ProjectStatus
from gtfs_explorer.infrastructure.duckdb.database import ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.workspace_recovery import (
    BackupCandidate,
    RecoveryInspection,
    WorkspaceAction,
    WorkspaceRecovery,
    inspect_recovery_state,
    restore_backup,
)


@dataclass(frozen=True)
class WorkspaceRecoveryResult:
    """Resultado auditable de la recuperación y sus siguientes pasos explícitos."""

    retry_job_ids: tuple[str, ...]
    actions: tuple[WorkspaceAction, ...]


class RecoverWorkspace:
    """Evita que un trabajo que sufrió un crash deje el proyecto en estado READY."""

    def __init__(self, database: ProjectDatabase) -> None:
        self._database = database
        self._filesystem = WorkspaceRecovery(database.temporary_directory)

    def execute(self) -> WorkspaceRecoveryResult:
        """Detecta trabajos incompletos, exige recuperación y aísla sus temporales."""
        with DuckDbUnitOfWork(self._database) as unit_of_work:
            retry_job_ids = unit_of_work.import_jobs.recover_interrupted()
            project = unit_of_work.projects.metadata()
            if retry_job_ids and project is not None:
                unit_of_work.projects.save_metadata(
                    ProjectMetadata(
                        project.project_id,
                        project.name,
                        ProjectStatus.RECOVERY_REQUIRED,
                    )
                )
        actions = self._filesystem.quarantine_import_temporary_directories()
        return WorkspaceRecoveryResult(retry_job_ids, actions)

    def cleanup_quarantine(self, *, confirmed: bool) -> tuple[WorkspaceAction, ...]:
        """Borra solamente cuarentenas verificadas cuando el usuario lo confirma."""
        return self._filesystem.cleanup_quarantine(confirmed=confirmed)


class RestoreWorkspace:
    """Ejecuta una restauración elegida por el usuario y validada en staging."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    def inspect(self) -> RecoveryInspection:
        """Expone el diagnóstico sin realizar ninguna mutación."""
        from gtfs_explorer.application.commands.open_project import ProjectWriterLock

        lock_state = ProjectWriterLock.probe(self._workspace).value
        return inspect_recovery_state(self._workspace, lock_state=lock_state)

    def execute(self, candidate: BackupCandidate) -> Path:
        """Restaura solo el candidato exacto seleccionado explícitamente."""
        return restore_backup(self._workspace, candidate)
