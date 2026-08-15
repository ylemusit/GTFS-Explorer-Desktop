"""Estado global y transiciones permitidas para el shell de escritorio."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class UiMode(StrEnum):
    """Estados visibles del shell, independientes de los widgets Qt."""

    NO_PROJECT = "NO_PROJECT"
    PROJECT_READY = "PROJECT_READY"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    JOB_RUNNING = "JOB_RUNNING"
    JOB_CANCELLING = "JOB_CANCELLING"


class UiAction(StrEnum):
    NEW_PROJECT = "NEW_PROJECT"
    OPEN_PROJECT = "OPEN_PROJECT"
    CLOSE_PROJECT = "CLOSE_PROJECT"
    IMPORT_FEED = "IMPORT_FEED"
    CANCEL_JOB = "CANCEL_JOB"
    SHOW_SETTINGS = "SHOW_SETTINGS"


@dataclass(frozen=True)
class UiState:
    """Única fuente de verdad para las acciones y el estado visible de la UI."""

    mode: UiMode = UiMode.NO_PROJECT

    @property
    def status_message(self) -> str:
        return {
            UiMode.NO_PROJECT: "Sin proyecto abierto.",
            UiMode.PROJECT_READY: "Proyecto abierto y listo.",
            UiMode.RECOVERY_REQUIRED: "El proyecto requiere recuperación antes de continuar.",
            UiMode.JOB_RUNNING: "Trabajo en curso.",
            UiMode.JOB_CANCELLING: "Cancelando trabajo en curso…",
        }[self.mode]

    def allows(self, action: UiAction) -> bool:
        """Indica si una acción es segura en el estado actual."""
        enabled = {
            UiMode.NO_PROJECT: {
                UiAction.NEW_PROJECT,
                UiAction.OPEN_PROJECT,
                UiAction.SHOW_SETTINGS,
            },
            UiMode.PROJECT_READY: {
                UiAction.NEW_PROJECT,
                UiAction.OPEN_PROJECT,
                UiAction.CLOSE_PROJECT,
                UiAction.IMPORT_FEED,
                UiAction.SHOW_SETTINGS,
            },
            UiMode.RECOVERY_REQUIRED: {
                UiAction.NEW_PROJECT,
                UiAction.OPEN_PROJECT,
                UiAction.CLOSE_PROJECT,
                UiAction.SHOW_SETTINGS,
            },
            UiMode.JOB_RUNNING: {UiAction.CANCEL_JOB},
            UiMode.JOB_CANCELLING: set(),
        }
        return action in enabled[self.mode]

    def project_opened(self, *, recovery_required: bool = False) -> "UiState":
        return UiState(UiMode.RECOVERY_REQUIRED if recovery_required else UiMode.PROJECT_READY)

    def project_closed(self) -> "UiState":
        if self.mode in {UiMode.JOB_RUNNING, UiMode.JOB_CANCELLING}:
            raise RuntimeError("No se puede cerrar el proyecto mientras hay un trabajo en curso.")
        return UiState()

    def job_started(self) -> "UiState":
        if not self.allows(UiAction.IMPORT_FEED):
            raise RuntimeError("No se puede iniciar un trabajo en el estado actual.")
        return UiState(UiMode.JOB_RUNNING)

    def cancellation_requested(self) -> "UiState":
        if self.mode is UiMode.JOB_RUNNING:
            return UiState(UiMode.JOB_CANCELLING)
        return self

    def job_finished(self, *, recovery_required: bool = False) -> "UiState":
        if self.mode not in {UiMode.JOB_RUNNING, UiMode.JOB_CANCELLING}:
            raise RuntimeError("No hay un trabajo en curso que finalizar.")
        return self.project_opened(recovery_required=recovery_required)
