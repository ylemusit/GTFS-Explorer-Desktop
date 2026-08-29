"""Resolución explícita de rutas para las distribuciones instalada y portable."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Callable

MINIMUM_FREE_BYTES = 100 * 1024 * 1024


class WorkspaceSelectionRequired(RuntimeError):
    """El modo portable no puede usar su workspace local con seguridad."""


class DirectoryKind(StrEnum):
    """Tipos de carpetas que la interfaz puede proponer al usuario."""

    PROJECTS = "projects"
    IMPORTS = "imports"
    EXPORTS = "exports"
    PMTILES_IMPORT = "pmtiles_import"
    DIAGNOSTICS = "diagnostics"


def application_resource_path(relative: str) -> Path:
    """Resuelve recursos propios desde el ejecutable o desde la raíz del repositorio."""
    executable_resource = Path(sys.executable).resolve().parent / relative
    if getattr(sys, "frozen", False) or executable_resource.exists():
        return executable_resource
    return Path(__file__).resolve().parents[4] / relative


@dataclass(frozen=True)
class ApplicationPaths:
    """Rutas de aplicación y de usuario, siempre separadas del directorio actual.

    ``workspace`` contiene datos técnicos locales (logs, settings, caché y
    temporales). Las carpetas de trabajo que el usuario debe encontrar con
    facilidad se resuelven desde ``documents_directory`` en la instalación
    normal. En portable se conserva el workspace relativo existente.
    """

    workspace: Path
    is_portable: bool
    documents_directory: Path = field(default_factory=lambda: default_documents_directory())

    @property
    def application_data_directory(self) -> Path:
        """Raíz técnica local de esta instalación o workspace portable."""

        return self.workspace

    @property
    def user_documents_directory(self) -> Path:
        """Raíz visible de documentos de GTFS Explorer."""

        return self.documents_directory / "GTFS Explorer"

    @property
    def cache_directory(self) -> Path:
        return self.workspace / "cache"

    @property
    def logs_directory(self) -> Path:
        return self.workspace / "logs"

    @property
    def projects_directory(self) -> Path:
        if self.is_portable:
            return self.workspace / "projects"
        return self.user_documents_directory / "Projects"

    @property
    def imports_directory(self) -> Path:
        if self.is_portable:
            return self.workspace / "imports"
        return self.user_documents_directory / "Imports"

    @property
    def exports_directory(self) -> Path:
        if self.is_portable:
            return self.workspace / "exports"
        return self.user_documents_directory / "Exports"

    @property
    def diagnostics_directory(self) -> Path:
        if self.is_portable:
            return self.workspace / "diagnostics"
        return self.user_documents_directory / "Diagnostics"

    @property
    def map_imports_directory(self) -> Path:
        """Ubicación sugerida para localizar fuentes PMTiles del usuario."""

        if self.is_portable:
            return self.workspace / "maps"
        return self.user_documents_directory / "Maps"

    @property
    def maps_directory(self) -> Path:
        """Biblioteca global P1-18, nunca dentro de Documents."""

        return self.workspace / "maps"

    @property
    def settings_path(self) -> Path:
        return self.workspace / "settings.json"

    @property
    def temporary_directory(self) -> Path:
        return self.workspace / "temp"

    def create_directories(self) -> None:
        """Crea solo raíces técnicas explícitamente solicitadas.

        Projects, Imports, Exports y Diagnostics se crean de forma lazy al
        abrir la operación correspondiente; no se crean durante el arranque.
        """

        for directory in (
            self.workspace,
            self.cache_directory,
            self.logs_directory,
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
    documents_directory: Path | None = None,
    documents_directory_resolver: Callable[[], Path] | None = None,
    minimum_free_bytes: int = MINIMUM_FREE_BYTES,
    portable_workspace_is_usable: Callable[[Path, int], bool] = _has_writable_space,
) -> ApplicationPaths:
    """Devuelve rutas técnicas y de usuario sin usar el cwd como fallback."""
    application_directory = executable_path.resolve().parent
    portable_workspace = application_directory / "workspace"
    documents_root = documents_directory or (
        documents_directory_resolver()
        if documents_directory_resolver
        else default_documents_directory()
    )
    if (application_directory / "portable.flag").is_file():
        if not portable_workspace_is_usable(portable_workspace, minimum_free_bytes):
            raise WorkspaceSelectionRequired(
                "El workspace portable no es escribible o no dispone de espacio suficiente."
            )
        return ApplicationPaths(
            workspace=portable_workspace,
            is_portable=True,
            documents_directory=documents_root,
        )

    app_data_root = local_app_data or _local_app_data_from_environment()
    return ApplicationPaths(
        workspace=app_data_root / "GTFS Explorer",
        is_portable=False,
        documents_directory=documents_root,
    )


def _local_app_data_from_environment() -> Path:
    return default_local_app_data_directory()


def default_local_app_data_directory() -> Path:
    """Obtiene una raíz local razonable en Windows y en entornos de desarrollo."""

    value = os.environ.get("LOCALAPPDATA")
    if value:
        return Path(value)
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Local"
    value = os.environ.get("XDG_DATA_HOME")
    return Path(value) if value else Path.home() / ".local" / "share"


def default_documents_directory() -> Path:
    """Resuelve Documents mediante Qt y mantiene un fallback multiplataforma.

    ``QStandardPaths`` conoce Documents redirigido, OneDrive y perfiles no
    estándar en Windows. La importación es lazy para que la infraestructura
    siga siendo utilizable en pruebas sin una QApplication.
    """

    try:
        from PySide6.QtCore import QStandardPaths

        value = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if value:
            return Path(value)
    except (ImportError, AttributeError, RuntimeError):
        pass
    return Path.home() / "Documents"
