"""Inventario y extracción ZIP sin permitir que una entrada escape del temporal."""

from __future__ import annotations

import hashlib
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable
from zipfile import ZipFile, ZipInfo

from gtfs_explorer.domain.errors import ImportCancelled, ImportSecurityError
from gtfs_explorer.domain.source import InputSource, InputSourceKind, SourceEntry, SourceManifest


@dataclass(frozen=True)
class ZipLimits:
    max_entries: int = 256
    max_compressed_bytes: int = 2 * 1024**3
    max_uncompressed_bytes: int = 20 * 1024**3
    max_entry_bytes: int = 10 * 1024**3
    max_compression_ratio: int = 200


_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class ZipSource:
    """Lector de ZIP que valida todo el índice antes de abrir contenido."""

    def __init__(self, limits: ZipLimits = ZipLimits()) -> None:
        self._limits = limits

    def inventory(self, source: InputSource) -> SourceManifest:
        if source.kind is not InputSourceKind.ARCHIVE:
            raise ValueError("ZipSource solo admite fuentes ARCHIVE.")
        with ZipFile(source.path) as archive:
            entries = self._validated_entries(archive.infolist())
            source_entries = tuple(
                SourceEntry(info.filename, info.file_size, _entry_sha256(archive, info))
                for info in entries
            )
        return SourceManifest.create(source, source_entries)

    def extract(
        self,
        source: InputSource,
        temporary_directory: Path,
        *,
        has_free_space: Callable[[int], bool],
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> SourceManifest:
        if source.kind is not InputSourceKind.ARCHIVE:
            raise ValueError("ZipSource solo admite fuentes ARCHIVE.")
        with ZipFile(source.path) as archive:
            entries = self._validated_entries(archive.infolist())
            required_bytes = sum(info.file_size for info in entries)
            if not has_free_space(required_bytes):
                raise ImportSecurityError("No hay espacio libre suficiente para extraer el ZIP.")
            temporary_root = temporary_directory.resolve()
            temporary_root.mkdir(parents=True, exist_ok=True)
            extracted: list[SourceEntry] = []
            for info in entries:
                if is_cancelled():
                    raise ImportCancelled("Extracción cancelada.")
                target = (temporary_root / info.filename).resolve()
                if target.parent != temporary_root:
                    raise ImportSecurityError("La entrada ZIP escapa del directorio temporal.")
                with archive.open(info) as input_file, target.open("xb") as output_file:
                    digest = hashlib.sha256()
                    while chunk := input_file.read(1024 * 1024):
                        if is_cancelled():
                            raise ImportCancelled("Extracción cancelada.")
                        if not has_free_space(len(chunk)):
                            raise ImportSecurityError(
                                "El espacio libre se agotó durante la extracción."
                            )
                        output_file.write(chunk)
                        digest.update(chunk)
                extracted.append(SourceEntry(info.filename, info.file_size, digest.hexdigest()))
        return SourceManifest.create(source, tuple(extracted))

    def _validated_entries(self, entries: list[ZipInfo]) -> list[ZipInfo]:
        if len(entries) > self._limits.max_entries:
            raise ImportSecurityError("El ZIP supera el número máximo de entradas.")
        total_compressed = sum(entry.compress_size for entry in entries)
        total_uncompressed = sum(entry.file_size for entry in entries)
        if total_compressed > self._limits.max_compressed_bytes:
            raise ImportSecurityError("El ZIP supera el tamaño comprimido máximo.")
        if total_uncompressed > self._limits.max_uncompressed_bytes:
            raise ImportSecurityError("El ZIP supera el tamaño descomprimido máximo.")
        seen: set[str] = set()
        valid: list[ZipInfo] = []
        for entry in entries:
            _validate_entry(entry, seen, self._limits)
            valid.append(entry)
        return valid


def _validate_entry(entry: ZipInfo, seen: set[str], limits: ZipLimits) -> None:
    path = PurePosixPath(entry.filename)
    if entry.is_dir() or path.is_absolute() or "\\" in entry.filename or ":" in entry.filename:
        raise ImportSecurityError(f"Nombre ZIP no permitido: {entry.filename}")
    if len(path.parts) != 1 or path.name in {"", ".", ".."} or ".." in path.parts:
        raise ImportSecurityError(f"Ruta ZIP no permitida: {entry.filename}")
    if path.stem.casefold() in _RESERVED_NAMES:
        raise ImportSecurityError(f"Nombre reservado de Windows: {entry.filename}")
    mode = entry.external_attr >> 16
    if stat.S_ISLNK(mode) or entry.flag_bits & 0x1:
        raise ImportSecurityError(f"Tipo o cifrado ZIP no permitido: {entry.filename}")
    if (
        entry.file_size > limits.max_entry_bytes
        or entry.file_size > max(entry.compress_size, 1) * limits.max_compression_ratio
    ):
        raise ImportSecurityError(f"Entrada ZIP supera sus límites: {entry.filename}")
    canonical_name = unicodedata.normalize("NFKC", entry.filename).casefold()
    if canonical_name in seen:
        raise ImportSecurityError(f"Colisión lógica de nombre: {entry.filename}")
    seen.add(canonical_name)


def _entry_sha256(archive: ZipFile, info: ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(info) as entry:
        for chunk in iter(lambda: entry.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
