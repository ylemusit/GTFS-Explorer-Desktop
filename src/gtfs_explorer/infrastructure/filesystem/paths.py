"""Resolución explícita de rutas para las distribuciones instalada y portable."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MINIMUM_FREE_BYTES = 100 * 1024 * 1024


class WorkspaceSelectionRequired(RuntimeError):
    """El modo portable no puede usar su workspace local con seguridad."""


def application_resource_path(relative: str) -> Path:
    """Resuelve recursos propios desde el ejecutable o desde la raíz del repositorio."""
    executable_resource = Path(sys.executable).resolve().parent / relative
    if getattr(sys, "frozen", False) or executable_resource.exists():
        return executable_resource
    return Path(__file__).resolve().parents[4] / relative


@dataclass(frozen=True)
class ApplicationPaths:
    """Rutas de datos de la aplicación, siempre separadas del directorio actual."""

    workspace: Path
    is_portable: bool

    @property
    def cache_directory(self) -> Path:
        return self.workspace / "cache"

    @property
    def logs_directory(self) -> Path:
        return self.workspace / "logs"

    @property
    def projects_directory(self) -> Path:
        return self.workspace / "projects"

    @property
    def settings_path(self) -> Path:
        return self.workspace / "settings.json"

    @property
    def temporary_directory(self) -> Path:
        return self.workspace / "temp"

    def create_directories(self) -> None:
        """Crea únicamente las carpetas de datos previamente resueltas."""
        for directory in (
            self.workspace,
            self.cache_directory,
            self.logs_directory,
            self.projects_directory,
            self.temporary_directory,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _has_writable_space(path: Path, minimum_free_bytes: int) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".gtfs-explorer-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return shutil.disk_usage(path).free >= minimum_free_bytes
    except OSError:
        return False


def resolve_application_paths(
    executable_path: Path,
    *,
    local_app_data: Path | None = None,
    minimum_free_bytes: int = MINIMUM_FREE_BYTES,
    portable_workspace_is_usable: Callable[[Path, int], bool] = _has_writable_space,
) -> ApplicationPaths:
    """Devuelve rutas de datos sin usar el cwd como fallback implícito."""
    application_directory = executable_path.resolve().parent
    portable_workspace = application_directory / "workspace"
    if (application_directory / "portable.flag").is_file():
        if not portable_workspace_is_usable(portable_workspace, minimum_free_bytes):
            raise WorkspaceSelectionRequired(
                "El workspace portable no es escribible o no dispone de espacio suficiente."
            )
        return ApplicationPaths(workspace=portable_workspace, is_portable=True)

    app_data_root = local_app_data or _local_app_data_from_environment()
    return ApplicationPaths(workspace=app_data_root / "GTFS Explorer", is_portable=False)


def _local_app_data_from_environment() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise RuntimeError("LOCALAPPDATA no está disponible para la instalación no portable.")
    return Path(value)
