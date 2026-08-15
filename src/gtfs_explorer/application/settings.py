"""Settings locales con rutas de proyecto siempre relativas al workspace."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

SETTINGS_VERSION = 1


@dataclass(frozen=True)
class Settings:
    recent_project_paths: tuple[PurePosixPath, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "version": SETTINGS_VERSION,
            "recent_project_paths": [path.as_posix() for path in self.recent_project_paths],
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
    path.write_text(json.dumps(settings.to_dict(), indent=2) + "\n", encoding="utf-8")


def relative_project_path(workspace: Path, project_path: Path) -> PurePosixPath:
    """Convierte una ruta de proyecto del workspace en su representación portable."""
    try:
        relative_path = project_path.resolve().relative_to(workspace.resolve())
    except ValueError as error:
        raise ValueError("La ruta del proyecto debe pertenecer al workspace.") from error
    return PurePosixPath(relative_path.as_posix())


def _settings_from_payload(payload: Any) -> Settings:
    if not isinstance(payload, dict) or set(payload) != {"version", "recent_project_paths"}:
        raise ValueError("settings.json no cumple el esquema de settings v1.")
    if payload["version"] != SETTINGS_VERSION:
        raise ValueError("La versión de settings no es compatible.")
    values = payload["recent_project_paths"]
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("recent_project_paths debe ser una lista de rutas relativas.")
    paths = tuple(PurePosixPath(value) for value in values)
    if any(path.is_absolute() or ".." in path.parts for path in paths):
        raise ValueError("Las rutas de proyecto deben ser relativas y no salir del workspace.")
    return Settings(recent_project_paths=paths)
