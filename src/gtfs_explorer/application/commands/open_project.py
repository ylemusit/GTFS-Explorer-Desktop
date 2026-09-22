"""Apertura exclusiva de proyectos persistentes y sus derivados descartables."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO

from gtfs_explorer.application.commands.recover_workspace import RecoverWorkspace
from gtfs_explorer.infrastructure.duckdb.database import (
    DatabaseCorruptionError,
    DatabaseSchemaError,
    DatabaseSettings,
    ProjectDatabase,
)
from gtfs_explorer.infrastructure.duckdb.editor_migration import migrate_editor_database
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.cache import CacheStore
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    reconcile_project_descriptor,
    save_project_descriptor,
)
from gtfs_explorer.infrastructure.filesystem.workspace_recovery import (
    RecoveryCandidateAvailableError,
    RecoveryState,
    create_recovery_snapshot,
    inspect_recovery_state,
    rebuild_descriptor_from_canonical,
)


class ProjectOpenError(RuntimeError):
    """No se puede abrir de forma segura el proyecto solicitado."""


class ProjectWriterLockedError(ProjectOpenError):
    """Otro proceso mantiene el bloqueo exclusivo de escritura."""


class _WriterLockContentionError(OSError):
    """El primitivo de locking del SO confirmó contención de writer."""


class WriterLockState(StrEnum):
    """Estado observable del sentinel después de consultar el lock del SO."""

    ACTIVE = "ACTIVE"
    STALE = "STALE"
    INVALID = "INVALID"


class ProjectWriterLock:
    """Lock exclusivo del SO con metadata mínima y sentinel recuperable tras crash.

    El descriptor ``.writer.lock`` no es la autoridad: la autoridad es el handle
    bloqueado por Windows (o ``flock`` en plataformas de desarrollo Unix). Por
    eso un fichero residual puede clasificarse como STALE y reutilizarse sin
    confiar únicamente en el PID, que puede haberse reutilizado.
    """

    LOCK_VERSION = 1
    _local_metadata: dict[Path, dict[str, object]] = {}

    def __init__(self, project_directory: Path) -> None:
        self._path = project_directory / ".writer.lock"
        self._handle: BinaryIO | None = None
        self._acquired = False
        self.state: WriterLockState | None = None
        self.metadata: dict[str, object] | None = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "lock_version": self.LOCK_VERSION,
            "pid": os.getpid(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            handle = self._path.open("a+b")
        except OSError as error:
            if self._has_active_windows_writer():
                self.state = WriterLockState.ACTIVE
                raise ProjectWriterLockedError(self._blocked_message()) from error
            raise
        try:
            self._lock_handle(handle)
        except _WriterLockContentionError as error:
            self._close_handle_quietly(handle)
            self.state = WriterLockState.ACTIVE
            raise ProjectWriterLockedError(self._blocked_message()) from error
        except OSError as error:
            # En Windows, un segundo handle puede alcanzar el bootstrap del
            # byte antes de descubrir el rango ya bloqueado. ``flush()``
            # falla entonces con PermissionError y ``close()`` puede repetir
            # ese fallo por el buffer pendiente. Solo es contención si una
            # lectura independiente confirma el byte bloqueado.
            self._close_handle_quietly(handle)
            if self._has_active_windows_writer():
                self.state = WriterLockState.ACTIVE
                raise ProjectWriterLockedError(self._blocked_message()) from error
            raise
        try:
            previous = self._read_metadata(handle)
            self.state = WriterLockState.STALE if previous is not None else WriterLockState.INVALID
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(record, sort_keys=True).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        except OSError as error:
            self._unlock_handle(handle)
            handle.close()
            raise ProjectOpenError(
                "No se ha podido escribir la metadata del bloqueo del proyecto."
            ) from error
        self._handle = handle
        self._acquired = True
        self.metadata = record
        self._local_metadata[self._path] = record

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            if self._handle is not None:
                self._unlock_handle(self._handle)
                self._handle.close()
            self._path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        finally:
            self._handle = None
            self._acquired = False
            self._local_metadata.pop(self._path, None)
            self.metadata = None

    @classmethod
    def probe(cls, project_directory: Path) -> WriterLockState:
        """Consulta el lock del SO sin escribir ni reemplazar su metadata."""
        path = project_directory / ".writer.lock"
        if not path.is_file():
            return WriterLockState.INVALID
        try:
            handle = path.open("r+b")
        except OSError:
            return WriterLockState.INVALID
        try:
            try:
                first_byte = handle.read(1)
            except OSError:
                return WriterLockState.ACTIVE
            if not first_byte:
                return WriterLockState.INVALID
            try:
                cls._lock_handle(handle)
            except OSError:
                return WriterLockState.ACTIVE
            previous = cls(project_directory)._read_metadata(handle)
            cls._unlock_handle(handle)
            return WriterLockState.STALE if previous is not None else WriterLockState.INVALID
        finally:
            handle.close()

    @staticmethod
    def _lock_handle(handle: BinaryIO) -> None:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            if handle.tell() == 0:
                handle.write(b" ")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                # Tras abrir, posicionar y publicar el byte de locking, este
                # primitivo solo señala que el rango ya está bloqueado.
                raise _WriterLockContentionError() from error
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_handle(handle: BinaryIO) -> None:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _close_handle_quietly(handle: BinaryIO) -> None:
        try:
            handle.close()
        except OSError:
            # Conserva el error de adquisición original: en Windows close()
            # puede reintentar el flush fallido de un buffer pendiente.
            pass

    def _has_active_windows_writer(self) -> bool:
        """Comprueba la contención real sin confundir ACLs con un writer.

        Un byte-range lock de Windows permite normalmente abrir el sentinel,
        pero impide leer su primer byte desde otro handle. Un fallo al abrir
        el fichero no prueba contención (puede ser una ACL), por lo que se
        conserva como error de filesystem.
        """
        if sys.platform != "win32":
            return False
        try:
            with self._path.open("rb") as probe:
                try:
                    probe.read(1)
                except PermissionError:
                    return True
        except OSError:
            return False
        return False

    def _read_metadata(self, handle: BinaryIO | None = None) -> dict[str, object] | None:
        try:
            if handle is None:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            else:
                handle.seek(0)
                payload = json.loads(handle.read().decode("utf-8"))
            if (
                isinstance(payload, dict)
                and payload.get("lock_version") == self.LOCK_VERSION
                and isinstance(payload.get("pid"), int)
                and isinstance(payload.get("created_at"), str)
            ):
                return payload
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            pass
        return None

    def _blocked_message(self) -> str:
        # En Windows el byte-range lock también impide abrir el sentinel para
        # lectura. Solo usamos metadata local para enriquecer el mensaje; la
        # decisión de bloqueo ya la tomó el OS lock.
        record = self._local_metadata.get(self._path) or self._read_metadata()
        if record is not None:
            return (
                f"El proyecto está en uso por otro escritor (PID {record['pid']}, "
                f"desde {record['created_at']}). Cierre esa instancia antes de continuar."
            )
        return "El proyecto está en uso por otro escritor; no se puede abrir como editable."


@dataclass
class OpenedProject:
    """Recursos de una apertura exclusiva; cierre siempre libera el escritor."""

    directory: Path
    database: ProjectDatabase
    cache: CacheStore
    descriptor: ProjectDescriptor
    _writer_lock: ProjectWriterLock

    def close(self) -> None:
        # Las conexiones DuckDB se abren por UoW y ya se cierran al salir de
        # cada contexto. La liberación del lock es siempre el último recurso.
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
        self._project_directory = project_directory.resolve()
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
            inspection = inspect_recovery_state(self._project_directory, lock_state="HELD")
            if inspection.state == RecoveryState.RESTORE_CANDIDATE_AVAILABLE:
                raise RecoveryCandidateAvailableError(inspection)
            if not inspection.database.supported:
                if inspection.database.reason_code == "UNAVAILABLE":
                    raise DatabaseCorruptionError("La base DuckDB del proyecto está corrupta.")
                if inspection.database.reason_code == "SCHEMA":
                    raise DatabaseSchemaError(
                        "La versión del esquema DuckDB no es compatible con esta apertura."
                    )
                raise ProjectOpenError(
                    "El proyecto no puede abrirse de forma segura y no hay una "
                    "recuperación validada. "
                    "Los archivos originales no se han modificado."
                )
            if inspection.descriptor_kind == "INVALID":
                rebuild_descriptor_from_canonical(self._project_directory)
            elif inspection.descriptor_kind == "RECOVERABLE_MISMATCH":
                snapshot = create_recovery_snapshot(self._project_directory, include_database=False)
                _ = snapshot
            database.initialize()
            database.validate_compatible()
            database.synchronize_schema_mirror()
            with DuckDbUnitOfWork(database) as unit_of_work:
                descriptor = reconcile_project_descriptor(self._project_directory, unit_of_work)
            migrate_editor_database(database)
            recovery = RecoverWorkspace(database).execute()
            if recovery.retry_job_ids:
                with DuckDbUnitOfWork(database) as unit_of_work:
                    project = unit_of_work.projects.metadata()
                    assert project is not None
                    descriptor = ProjectDescriptor.from_metadata(
                        project, unit_of_work.feeds.latest_metadata(), self._project_directory
                    )
                    save_project_descriptor(self._project_directory / "project.json", descriptor)
            cache = CacheStore(self._project_directory / "cache")
            return OpenedProject(self._project_directory, database, cache, descriptor, writer_lock)
        except Exception:
            writer_lock.release()
            raise
