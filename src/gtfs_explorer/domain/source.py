"""Contrato puro para describir entradas de importación antes de abrirlas."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

SOURCE_MANIFEST_VERSION = 1


class InputSourceKind(StrEnum):
    ARCHIVE = "archive"
    DIRECTORY = "directory"
    FILE = "file"


class SourceEntryState(StrEnum):
    DISCOVERED = "discovered"
    DUPLICATE_LOGICAL_NAME = "duplicate_logical_name"


@dataclass(frozen=True)
class InputSource:
    """Entrada local aún no abierta ni validada como feed GTFS."""

    path: Path
    kind: InputSourceKind


@dataclass(frozen=True)
class SourceEntry:
    """Archivo inventariado con hash de contenido, no hash de su contenedor."""

    original_name: str
    size_bytes: int
    content_sha256: str
    state: SourceEntryState = SourceEntryState.DISCOVERED

    @property
    def canonical_name(self) -> str:
        return unicodedata.normalize("NFKC", self.original_name).casefold()

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_name": self.canonical_name,
            "content_sha256": self.content_sha256,
            "original_name": self.original_name,
            "size_bytes": self.size_bytes,
            "state": self.state,
        }


@dataclass(frozen=True)
class SourceManifest:
    """Inventario serializable, determinista y libre de rutas locales."""

    source_kind: InputSourceKind
    entries: tuple[SourceEntry, ...]
    container_sha256: str | None = None

    @classmethod
    def create(cls, source: InputSource, entries: tuple[SourceEntry, ...]) -> "SourceManifest":
        seen_names: set[str] = set()
        normalized_entries: list[SourceEntry] = []
        for entry in sorted(entries, key=lambda value: (value.canonical_name, value.original_name)):
            state = entry.state
            if entry.canonical_name in seen_names:
                state = SourceEntryState.DUPLICATE_LOGICAL_NAME
            seen_names.add(entry.canonical_name)
            normalized_entries.append(
                SourceEntry(entry.original_name, entry.size_bytes, entry.content_sha256, state)
            )
        container_hash = (
            _file_sha256(source.path) if source.kind is InputSourceKind.ARCHIVE else None
        )
        return cls(source.kind, tuple(normalized_entries), container_hash)

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "manifest_version": SOURCE_MANIFEST_VERSION,
            "source_kind": self.source_kind,
            "container_sha256": self.container_sha256,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
