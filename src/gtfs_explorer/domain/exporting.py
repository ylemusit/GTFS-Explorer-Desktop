"""Contratos de dominio para resultados de exportación locales."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


class ExportError(RuntimeError):
    """Una exportación no pudo completar su salida de forma segura."""


class ExportCancelled(ExportError):
    """La exportación se canceló antes de publicar el archivo final."""


class ExportDestinationError(ExportError):
    """El destino solicitado no es apto para una salida de usuario."""


class ExportDestinationExistsError(ExportDestinationError):
    """El destino ya existe y no se autorizó sobrescribirlo."""


@dataclass(frozen=True)
class ExportManifest:
    """Evidencia mínima, portable y sin rutas absolutas de una salida escrita."""

    artifact_name: str
    sha256: str
    size_bytes: int
    manifest_name: str
    schema_version: int = 1
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_name or Path(self.artifact_name).name != self.artifact_name:
            raise ValueError("El manifiesto debe contener solo el nombre del artefacto.")
        if not self.manifest_name or Path(self.manifest_name).name != self.manifest_name:
            raise ValueError("El manifiesto debe contener solo su propio nombre.")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("El hash SHA-256 de la exportación no es válido.")
        if self.size_bytes < 0:
            raise ValueError("El tamaño de una exportación no puede ser negativo.")
