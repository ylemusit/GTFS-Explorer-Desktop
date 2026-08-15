"""Estados y señalización cooperativa del trabajo de importación."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import Event


class ImportPhase(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    STAGING = "STAGING"
    NORMALIZING = "NORMALIZING"
    VALIDATING = "VALIDATING"
    COMMITTING = "COMMITTING"
    CLEANUP = "CLEANUP"


@dataclass(frozen=True)
class ImportProgress:
    phase: ImportPhase
    completed_steps: int
    total_steps: int

    @property
    def fraction(self) -> float:
        return self.completed_steps / self.total_steps


class CancelToken:
    """Cancelación explícita y segura para consultar entre pasos conocidos."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()
