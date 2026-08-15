"""Recupera trabajos interrumpidos al abrir un proyecto."""

from __future__ import annotations

from dataclasses import dataclass

from gtfs_explorer.domain.project import ProjectMetadata, ProjectStatus
from gtfs_explorer.infrastructure.duckdb.database import ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.workspace_recovery import (
    WorkspaceAction,
    WorkspaceRecovery,
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
