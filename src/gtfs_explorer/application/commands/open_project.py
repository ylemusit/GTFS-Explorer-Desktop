"""Apertura exclusiva de proyectos persistentes y sus derivados descartables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from gtfs_explorer.application.commands.recover_workspace import RecoverWorkspace
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.cache import CacheStore
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    reconcile_project_descriptor,
    save_project_descriptor,
)


class ProjectOpenError(RuntimeError):
    """No se puede abrir de forma segura el proyecto solicitado."""


class ProjectWriterLockedError(ProjectOpenError):
    """Otro proceso mantiene el bloqueo exclusivo de escritura."""


class ProjectWriterLock:
    """Lock cooperativo de proceso con evidencia suficiente para recuperación manual segura."""

    def __init__(self, project_directory: Path) -> None:
        self._path = project_directory / ".writer.lock"
        self._acquired = False

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "pid": os.getpid(),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with self._path.open("x", encoding="utf-8") as output:
                json.dump(record, output, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError as error:
            raise ProjectWriterLockedError(self._blocked_message()) from error
        except OSError as error:
            raise ProjectOpenError(
                "No se ha podido crear el bloqueo de escritura del proyecto."
            ) from error
        self._acquired = True

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
        finally:
            self._acquired = False

    def _blocked_message(self) -> str:
        try:
            record = json.loads(self._path.read_text(encoding="utf-8"))
            pid = record.get("pid")
            acquired_at = record.get("acquired_at")
            if isinstance(pid, int) and isinstance(acquired_at, str):
                return (
                    f"El proyecto ya tiene un escritor activo (PID {pid}, desde {acquired_at}). "
                    "El bloqueo no se recupera automáticamente; compruebe ese proceso "
                    "antes de eliminarlo."
                )
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return "El proyecto ya tiene un escritor activo; el bloqueo no se recupera automáticamente."


@dataclass
class OpenedProject:
    """Recursos de una apertura exclusiva; cierre siempre libera el escritor."""

    directory: Path
    database: ProjectDatabase
    cache: CacheStore
    descriptor: ProjectDescriptor
    _writer_lock: ProjectWriterLock

    def close(self) -> None:
        self._writer_lock.release()

    def __enter__(self) -> "OpenedProject":
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        self.close()


class OpenProject:
    """Abre un proyecto existente sin permitir escritores simultáneos."""

    def __init__(
        self, project_directory: Path, *, settings: DatabaseSettings | None = None
    ) -> None:
        self._project_directory = project_directory
        self._settings = settings

    def execute(self) -> OpenedProject:
        """Valida el descriptor contra DuckDB y prepara una caché descartable."""
        database_path = self._project_directory / "data.duckdb"
        if not self._project_directory.is_dir() or not database_path.is_file():
            raise ProjectOpenError("La carpeta no contiene un proyecto GTFS Explorer válido.")

        writer_lock = ProjectWriterLock(self._project_directory)
        writer_lock.acquire()
        try:
            database = ProjectDatabase(
                database_path,
                self._project_directory / "temp",
                settings=self._settings or DatabaseSettings(memory_limit="512MB"),
            )
            recovery = RecoverWorkspace(database).execute()
            with DuckDbUnitOfWork(database) as unit_of_work:
                if recovery.retry_job_ids:
                    project = unit_of_work.projects.metadata()
                    assert project is not None
                    descriptor = ProjectDescriptor.from_metadata(
                        project, unit_of_work.feeds.latest_metadata(), self._project_directory
                    )
                    save_project_descriptor(self._project_directory / "project.json", descriptor)
                else:
                    descriptor = reconcile_project_descriptor(self._project_directory, unit_of_work)
            cache = CacheStore(self._project_directory / "cache")
            return OpenedProject(self._project_directory, database, cache, descriptor, writer_lock)
        except Exception:
            writer_lock.release()
            raise
