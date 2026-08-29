"""API de aplicación aislada para el historial de operaciones."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from gtfs_explorer.domain.operations import Operation, OperationStatus, OperationType, utc_now_naive
from gtfs_explorer.domain.ports import OperationRepository, PagedResult, PageRequest


class OperationHistory:
    """Coordina el ledger sin conectar todavía pipelines productivos."""

    def __init__(
        self, repository: OperationRepository, *, clock: Callable[[], datetime] = utc_now_naive
    ) -> None:
        self._repository = repository
        self._clock = clock

    def start_operation(
        self, operation_id: str, project_id: str, operation_type: OperationType
    ) -> None:
        self._repository.start(operation_id, project_id, operation_type, self._clock())

    def finish_operation(
        self, operation_id: str, status: OperationStatus, error_code: str | None = None
    ) -> None:
        self._repository.finish(operation_id, status, self._clock(), error_code)

    def attach_import_detail(self, operation_id: str, feed_id: str, job_id: str) -> None:
        self._repository.attach_import_detail(operation_id, feed_id, job_id)

    def attach_validation_detail(
        self, operation_id: str, feed_id: str, validation_batch_id: str | None = None
    ) -> None:
        self._repository.attach_validation_detail(operation_id, feed_id, validation_batch_id)

    def attach_export_detail(
        self,
        operation_id: str,
        feed_id: str,
        export_format: str,
        artifact_name: str | None = None,
        artifact_sha256: str | None = None,
        artifact_size_bytes: int | None = None,
    ) -> None:
        self._repository.attach_export_detail(
            operation_id,
            feed_id,
            export_format,
            artifact_name,
            artifact_sha256,
            artifact_size_bytes,
        )

    def list_operations(
        self,
        project_id: str,
        page: PageRequest,
        operation_type: OperationType | None = None,
        status: OperationStatus | None = None,
    ) -> PagedResult[Operation]:
        return self._repository.list_operations(project_id, page, operation_type, status)
