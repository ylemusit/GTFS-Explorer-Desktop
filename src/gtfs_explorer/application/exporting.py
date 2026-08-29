"""Ciclo de vida de las exportaciones de feed y su ledger persistente."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from gtfs_explorer.domain.exporting import (
    ExportDestinationError,
    ExportError,
    ExportManifest,
)
from gtfs_explorer.domain.operations import OperationStatus, OperationType, utc_now_naive
from gtfs_explorer.infrastructure.duckdb.database import ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork


class ExportResult(Protocol):
    @property
    def manifest(self) -> ExportManifest: ...


class FeedExportLifecycle:
    """Orquesta START, escritura local y cierre durable de una exportación.

    DuckDB y el filesystem no comparten una transacción ACID. Por eso START se
    confirma antes de escribir y el cierre se confirma después de publicar. Si
    el segundo commit falla, se conserva RUNNING para derivar INTERRUPTED al
    reabrir, sin borrar un artefacto que ya fue publicado.
    """

    def execute(
        self,
        database: ProjectDatabase,
        project_id: str,
        feed_id: str,
        export_format: str,
        writer: Callable[[str], ExportResult],
    ) -> ExportResult:
        operation_id = str(uuid4())
        self._start(database, operation_id, project_id, feed_id, export_format)
        try:
            result = writer(operation_id)
        except Exception as error:
            self._finish_failed(database, operation_id, error)
            raise
        try:
            with DuckDbUnitOfWork(database) as unit_of_work:
                unit_of_work.operations.update_export_detail(
                    operation_id,
                    result.manifest.artifact_name,
                    result.manifest.sha256,
                    result.manifest.size_bytes,
                )
                unit_of_work.operations.finish(operation_id, OperationStatus.COMPLETED, _now())
        except Exception:
            # El rollback deliberado conserva START como RUNNING.
            raise
        return result

    @staticmethod
    def _start(
        database: ProjectDatabase,
        operation_id: str,
        project_id: str,
        feed_id: str,
        export_format: str,
    ) -> None:
        with DuckDbUnitOfWork(database) as unit_of_work:
            unit_of_work.operations.start(operation_id, project_id, OperationType.EXPORT, _now())
            unit_of_work.operations.attach_export_detail(operation_id, feed_id, export_format)

    @staticmethod
    def _finish_failed(database: ProjectDatabase, operation_id: str, error: Exception) -> None:
        error_code = _error_code(error)
        with DuckDbUnitOfWork(database) as unit_of_work:
            unit_of_work.operations.finish(operation_id, OperationStatus.FAILED, _now(), error_code)


def _now() -> datetime:
    return utc_now_naive()


def _error_code(error: Exception) -> str:
    if isinstance(error, ExportDestinationError):
        return "EXPORT_PREPARE_FAILED"
    if isinstance(error, ExportError):
        return "EXPORT_WRITE_FAILED"
    return "EXPORT_PREPARE_FAILED"
