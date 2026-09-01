"""Settings locales y preferencias de carpetas de GTFS Explorer."""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from gtfs_explorer.infrastructure.filesystem.paths import ApplicationPaths, DirectoryKind

SETTINGS_VERSION = 1

_DIRECTORY_FIELDS: dict[DirectoryKind, str] = {
    DirectoryKind.PROJECTS: "last_project_dir",
    DirectoryKind.IMPORTS: "last_import_dir",
    DirectoryKind.EXPORTS: "last_export_dir",
    DirectoryKind.PMTILES_IMPORT: "last_pmtiles_import_dir",
    DirectoryKind.DIAGNOSTICS: "last_diagnostic_dir",
}
_LAYOUT_FIELD = "explore_splitter_state"
_MAP_GEOMETRY_FIELD = "map_window_geometry"
_MAP_MAXIMIZED_FIELD = "map_window_maximized"
_OPTIONAL_SETTINGS_FIELDS = frozenset(
    (*_DIRECTORY_FIELDS.values(), _LAYOUT_FIELD, _MAP_GEOMETRY_FIELD, _MAP_MAXIMIZED_FIELD)
)


@dataclass(frozen=True)
class Settings:
    recent_project_paths: tuple[PurePosixPath, ...] = ()
    last_project_dir: Path | None = None
    last_import_dir: Path | None = None
    last_export_dir: Path | None = None
    last_pmtiles_import_dir: Path | None = None
    last_diagnostic_dir: Path | None = None
    explore_splitter_state: bytes | None = None
    map_window_geometry: bytes | None = None
    map_window_maximized: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "version": SETTINGS_VERSION,
            "recent_project_paths": [path.as_posix() for path in self.recent_project_paths],
            "last_project_dir": _serialise_path(self.last_project_dir),
            "last_import_dir": _serialise_path(self.last_import_dir),
            "last_export_dir": _serialise_path(self.last_export_dir),
            "last_pmtiles_import_dir": _serialise_path(self.last_pmtiles_import_dir),
            "last_diagnostic_dir": _serialise_path(self.last_diagnostic_dir),
            _LAYOUT_FIELD: _serialise_splitter_state(self.explore_splitter_state),
            _MAP_GEOMETRY_FIELD: _serialise_splitter_state(self.map_window_geometry),
            _MAP_MAXIMIZED_FIELD: self.map_window_maximized,
        }


def load_settings(path: Path) -> Settings:
    """Carga settings válidos; un archivo inexistente representa la configuración inicial."""
    if not path.exists():
        return Settings()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _settings_from_payload(payload)


def save_settings(path: Path, settings: Settings) -> None:
    """Persiste los settings en su ruta ya resuelta, sin crear rutas de proyecto externas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def relative_project_path(workspace: Path, project_path: Path) -> PurePosixPath:
    """Convierte una ruta de proyecto del workspace en su representación portable."""
    try:
        relative_path = project_path.resolve().relative_to(workspace.resolve())
    except ValueError as error:
        raise ValueError("La ruta del proyecto debe pertenecer al workspace.") from error
    return PurePosixPath(relative_path.as_posix())


class DirectoryPreferences:
    """Resuelve defaults y recuerda carpetas globales sin tocar un proyecto.

    El settings es local al escritorio. Una preferencia inválida, ausente o
    no accesible se descarta en la resolución y devuelve el default de su tipo;
    recordar una carpeta es una mejora de UX y nunca debe bloquear una
    operación principal.
    """

    def __init__(
        self,
        paths: ApplicationPaths,
        *,
        settings: Settings | None = None,
        persist: bool = True,
    ) -> None:
        self._paths = paths
        self._persist = persist
        if settings is not None:
            self._settings = settings
        elif persist:
            try:
                self._settings = load_settings(paths.settings_path)
            except (OSError, UnicodeError, ValueError):
                self._settings = Settings()
        else:
            self._settings = Settings()

    @property
    def settings(self) -> Settings:
        """Preferencias actuales, para pruebas y composición de la UI."""

        return self._settings

    def default_directory(self, kind: DirectoryKind | str) -> Path:
        """Devuelve el default estable sin crear ninguna carpeta."""

        directory_kind = _directory_kind(kind)
        directories = {
            DirectoryKind.PROJECTS: self._paths.projects_directory,
            DirectoryKind.IMPORTS: self._paths.imports_directory,
            DirectoryKind.EXPORTS: self._paths.exports_directory,
            DirectoryKind.PMTILES_IMPORT: self._paths.map_imports_directory,
            DirectoryKind.DIAGNOSTICS: self._paths.diagnostics_directory,
        }
        return directories[directory_kind]

    def initial_directory(self, kind: DirectoryKind | str) -> Path:
        """Devuelve la última carpeta accesible o el default correspondiente."""

        directory_kind = _directory_kind(kind)
        field_name = _DIRECTORY_FIELDS[directory_kind]
        remembered = getattr(self._settings, field_name)
        if isinstance(remembered, Path) and _usable_directory(
            remembered, writable=_requires_write(directory_kind)
        ):
            return remembered
        return self.default_directory(directory_kind)

    def dialog_directory(self, kind: DirectoryKind | str) -> Path:
        """Prepara lazymente el inicio de un diálogo y ofrece un fallback seguro."""

        directory_kind = _directory_kind(kind)
        candidate = self.initial_directory(directory_kind)
        writable = _requires_write(directory_kind)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            if _usable_directory(candidate, writable=writable):
                return candidate
        except OSError:
            pass
        return _nearest_usable_directory(candidate.parent, writable=writable)

    def remember(self, kind: DirectoryKind | str, directory: Path) -> bool:
        """Recuerda una carpeta accesible; un fallo de settings no rompe la UX."""

        directory_kind = _directory_kind(kind)
        candidate = Path(directory)
        if candidate.is_file():
            candidate = candidate.parent
        if not _usable_directory(candidate, writable=False):
            return False
        if directory_kind is DirectoryKind.PROJECTS:
            self._settings = replace(self._settings, last_project_dir=candidate)
        elif directory_kind is DirectoryKind.IMPORTS:
            self._settings = replace(self._settings, last_import_dir=candidate)
        elif directory_kind is DirectoryKind.EXPORTS:
            self._settings = replace(self._settings, last_export_dir=candidate)
        elif directory_kind is DirectoryKind.PMTILES_IMPORT:
            self._settings = replace(self._settings, last_pmtiles_import_dir=candidate)
        else:
            self._settings = replace(self._settings, last_diagnostic_dir=candidate)
        if not self._persist:
            return True
        try:
            save_settings(self._paths.settings_path, self._settings)
        except (OSError, UnicodeError, ValueError):
            return False
        return True

    def remember_file(self, kind: DirectoryKind | str, file_path: Path) -> bool:
        """Recuerda el directorio contenedor de un archivo seleccionado."""

        return self.remember(kind, Path(file_path).parent)

    def remember_explore_splitter_state(self, state: bytes) -> bool:
        """Recuerda el estado Qt del workspace de Explorar en settings.json."""

        if not state:
            return False
        self._settings = replace(self._settings, explore_splitter_state=bytes(state))
        if not self._persist:
            return True
        try:
            save_settings(self._paths.settings_path, self._settings)
        except (OSError, UnicodeError, ValueError):
            return False
        return True

    def remember_map_window_geometry(self, geometry: bytes, maximized: bool) -> bool:
        """Persiste la geometría nativa de la ventana de mapa."""
        if not geometry:
            return False
        self._settings = replace(
            self._settings, map_window_geometry=bytes(geometry), map_window_maximized=maximized
        )
        if not self._persist:
            return True
        try:
            save_settings(self._paths.settings_path, self._settings)
        except (OSError, UnicodeError, ValueError):
            return False
        return True


def _settings_from_payload(payload: Any) -> Settings:
    required = {"version", "recent_project_paths"}
    allowed = required | _OPTIONAL_SETTINGS_FIELDS
    if not isinstance(payload, dict) or not required.issubset(payload) or set(payload) - allowed:
        raise ValueError("settings.json no cumple el esquema de settings v1.")
    if payload["version"] != SETTINGS_VERSION:
        raise ValueError("La versión de settings no es compatible.")
    values = payload["recent_project_paths"]
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("recent_project_paths debe ser una lista de rutas relativas.")
    paths = tuple(PurePosixPath(value) for value in values)
    if any(path.is_absolute() or ".." in path.parts for path in paths):
        raise ValueError("Las rutas de proyecto deben ser relativas y no salir del workspace.")
    return Settings(
        recent_project_paths=paths,
        last_project_dir=_optional_path(payload, "last_project_dir"),
        last_import_dir=_optional_path(payload, "last_import_dir"),
        last_export_dir=_optional_path(payload, "last_export_dir"),
        last_pmtiles_import_dir=_optional_path(payload, "last_pmtiles_import_dir"),
        last_diagnostic_dir=_optional_path(payload, "last_diagnostic_dir"),
        explore_splitter_state=_optional_splitter_state(payload),
        map_window_geometry=_optional_splitter_state(payload, _MAP_GEOMETRY_FIELD),
        map_window_maximized=_optional_bool(payload, _MAP_MAXIMIZED_FIELD),
    )


def _serialise_path(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _optional_path(payload: dict[str, object], field_name: str) -> Path | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} debe ser una ruta o null.")
    return Path(value)


def _serialise_splitter_state(state: bytes | None) -> str | None:
    return base64.b64encode(state).decode("ascii") if state else None


def _optional_splitter_state(
    payload: dict[str, object], field_name: str = _LAYOUT_FIELD
) -> bytes | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} debe ser un estado Qt codificado o null.")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError(f"{field_name} no es válido.") from error


def _optional_bool(payload: dict[str, object], field_name: str) -> bool:
    value = payload.get(field_name, False)
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} debe ser booleano.")
    return value


def _directory_kind(kind: DirectoryKind | str) -> DirectoryKind:
    try:
        return DirectoryKind(kind)
    except ValueError as error:
        raise ValueError(f"Tipo de carpeta no soportado: {kind}") from error


def _requires_write(kind: DirectoryKind) -> bool:
    return kind in {DirectoryKind.PROJECTS, DirectoryKind.EXPORTS, DirectoryKind.DIAGNOSTICS}


def _usable_directory(path: Path, *, writable: bool) -> bool:
    try:
        if not path.is_dir() or not os.access(path, os.R_OK | os.X_OK):
            return False
        return not writable or os.access(path, os.W_OK)
    except OSError:
        return False


def _nearest_usable_directory(path: Path, *, writable: bool) -> Path:
    candidate = path
    while candidate != candidate.parent:
        if _usable_directory(candidate, writable=writable):
            return candidate
        candidate = candidate.parent
    if _usable_directory(candidate, writable=writable):
        return candidate
    return path
