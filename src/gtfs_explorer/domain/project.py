"""Metadatos persistibles de proyecto, feed y trabajos de importación."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProjectStatus(StrEnum):
    READY = "READY"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class FeedStatus(StrEnum):
    IMPORTED = "IMPORTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    SUCCEEDED = "SUCCEEDED"
    READY = "READY"
    INVALID = "INVALID"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ProjectMetadata:
    project_id: str
    name: str
    status: ProjectStatus


@dataclass(frozen=True)
class FeedMetadata:
    feed_id: str
    project_id: str
    source_name: str
    manifest_sha256: str
    import_mode: str
    spec_revision: str
    status: FeedStatus

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.manifest_sha256):
            raise ValueError("El hash SHA-256 del manifiesto no es válido.")


@dataclass(frozen=True)
class ImportJobMetadata:
    job_id: str
    feed_id: str
    state: JobState
    phase: str = "PENDING"
    progress: float = 0.0
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("El progreso del trabajo debe estar entre cero y uno.")
