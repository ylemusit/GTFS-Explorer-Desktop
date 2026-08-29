"""Contrato tipado del ledger persistente de operaciones."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import PurePath

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class OperationType(StrEnum):
    IMPORT = "IMPORT"
    VALIDATION = "VALIDATION"
    EXPORT = "EXPORT"


class OperationStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class OperationDisplayStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


def utc_now_naive() -> datetime:
    """Reloj durable del ledger: UTC sin zona para TIMESTAMP DuckDB."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def display_status(
    operation: "Operation", active_runtime_ids: frozenset[str]
) -> OperationDisplayStatus:
    if (
        operation.status is OperationStatus.RUNNING
        and operation.operation_id not in active_runtime_ids
    ):
        return OperationDisplayStatus.INTERRUPTED
    return OperationDisplayStatus(operation.status)


@dataclass(frozen=True)
class Operation:
    operation_id: str
    project_id: str
    operation_type: OperationType
    status: OperationStatus
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    feed_id: str | None = None
    job_id: str | None = None
    validation_batch_id: str | None = None
    validation_result: str | None = None
    validation_issue_count: int | None = None
    export_format: str | None = None
    artifact_name: str | None = None
    artifact_sha256: str | None = None
    artifact_size_bytes: int | None = None
    feed_name: str | None = None


def validate_error_code(status: OperationStatus, error_code: str | None) -> None:
    if status in (OperationStatus.RUNNING, OperationStatus.COMPLETED) and error_code is not None:
        raise ValueError("Las operaciones en curso o completadas no admiten código de error.")
    if error_code is not None and not _ERROR_CODE.fullmatch(error_code):
        raise ValueError("El código de error debe ser un identificador estable en mayúsculas.")
    if status is OperationStatus.CANCELLED and error_code not in (None, "CANCELLED"):
        raise ValueError("Una cancelación solo admite el código CANCELLED.")


def validate_utc_naive(value: datetime) -> None:
    if value.tzinfo is not None:
        raise ValueError("Los timestamps persistidos deben ser UTC naive.")


def validate_artifact(
    artifact_name: str | None, artifact_sha256: str | None, artifact_size_bytes: int | None
) -> tuple[str | None, str | None]:
    if artifact_name is not None and (
        PurePath(artifact_name).is_absolute() or "/" in artifact_name or "\\" in artifact_name
    ):
        raise ValueError("El nombre de artefacto debe ser relativo y no contener rutas.")
    normalized_hash = artifact_sha256.lower() if artifact_sha256 is not None else None
    if normalized_hash is not None and not _SHA256.fullmatch(normalized_hash):
        raise ValueError("El hash SHA-256 del artefacto no es válido.")
    if artifact_size_bytes is not None and artifact_size_bytes < 0:
        raise ValueError("El tamaño del artefacto no puede ser negativo.")
    return artifact_name, normalized_hash
