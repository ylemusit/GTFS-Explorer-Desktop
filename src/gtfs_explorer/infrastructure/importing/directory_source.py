"""Inventario no destructivo de directorios y CSV compatibles."""

from __future__ import annotations

import hashlib
from pathlib import Path

from gtfs_explorer.domain.errors import ImportSecurityError
from gtfs_explorer.domain.source import InputSource, InputSourceKind, SourceEntry, SourceManifest


class DirectorySource:
    """Inventaría solo archivos regulares en la raíz, sin seguir enlaces."""

    def inventory(self, source: InputSource) -> SourceManifest:
        if source.kind is InputSourceKind.FILE:
            if source.path.suffix.casefold() != ".csv":
                raise ImportSecurityError("El modo compatible solo admite archivos .csv.")
            return SourceManifest.create(source, (self._entry(source.path),))
        if source.kind is not InputSourceKind.DIRECTORY or not source.path.is_dir():
            raise ValueError("DirectorySource requiere un directorio o un archivo CSV.")
        entries: list[SourceEntry] = []
        for path in sorted(source.path.iterdir(), key=lambda value: value.name.casefold()):
            if path.is_symlink() or not path.is_file():
                raise ImportSecurityError(f"Entrada de directorio no permitida: {path.name}")
            entries.append(self._entry(path))
        return SourceManifest.create(source, tuple(entries))

    @staticmethod
    def _entry(path: Path) -> SourceEntry:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return SourceEntry(path.name, path.stat().st_size, digest)
