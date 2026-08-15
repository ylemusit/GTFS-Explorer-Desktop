"""Pruebas del contrato de fuentes previo a cualquier apertura de ZIP."""

from __future__ import annotations

import hashlib
from pathlib import Path

from gtfs_explorer.domain.source import (
    InputSource,
    InputSourceKind,
    SourceEntry,
    SourceEntryState,
    SourceManifest,
)


def _entry(name: str, contents: bytes = b"fixture") -> SourceEntry:
    return SourceEntry(name, len(contents), hashlib.sha256(contents).hexdigest())


def test_empty_directory_manifest_is_deterministic_and_has_no_path(tmp_path: Path) -> None:
    source = InputSource(tmp_path / "Carpeta ñ", InputSourceKind.DIRECTORY)
    manifest = SourceManifest.create(source, ())

    assert manifest.to_json() == SourceManifest.create(source, ()).to_json()
    assert str(source.path) not in manifest.to_json()
    assert manifest.entries == ()


def test_archive_keeps_container_hash_and_content_hashes_separately(tmp_path: Path) -> None:
    archive = tmp_path / "entrada.zip"
    archive.write_bytes(b"container")
    manifest = SourceManifest.create(
        InputSource(archive, InputSourceKind.ARCHIVE),
        (_entry("stops.txt", b"contents"),),
    )

    assert manifest.container_sha256 == hashlib.sha256(b"container").hexdigest()
    assert manifest.entries[0].content_sha256 == hashlib.sha256(b"contents").hexdigest()


def test_unicode_and_case_equivalent_names_are_marked_as_logical_duplicates(tmp_path: Path) -> None:
    manifest = SourceManifest.create(
        InputSource(tmp_path / "entrada", InputSourceKind.DIRECTORY),
        (_entry("Stops.TXT"), _entry("stops.txt")),
    )

    assert manifest.entries[1].state is SourceEntryState.DUPLICATE_LOGICAL_NAME
    assert (
        manifest.manifest_sha256
        == SourceManifest.create(
            InputSource(tmp_path / "otra-ruta", InputSourceKind.DIRECTORY),
            (_entry("stops.txt"), _entry("Stops.TXT")),
        ).manifest_sha256
    )
