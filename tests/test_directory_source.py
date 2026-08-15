"""Pruebas de inventario no destructivo de directorios y CSV."""

from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_explorer.domain.errors import ImportSecurityError
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.infrastructure.importing.directory_source import DirectorySource


def test_directory_and_equivalent_csv_keep_logical_manifest(tmp_path: Path) -> None:
    directory = tmp_path / "fuente ñ"
    directory.mkdir()
    csv_path = directory / "stops.txt"
    csv_path.write_text("stop_id\nS1\n", encoding="utf-8")
    manifest = DirectorySource().inventory(InputSource(directory, InputSourceKind.DIRECTORY))
    assert manifest.entries[0].original_name == "stops.txt"
    assert csv_path.read_text(encoding="utf-8") == "stop_id\nS1\n"


def test_compatible_file_requires_csv_and_directory_rejects_links(tmp_path: Path) -> None:
    csv_path = tmp_path / "partial.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")
    assert DirectorySource().inventory(InputSource(csv_path, InputSourceKind.FILE)).entries
    with pytest.raises(ImportSecurityError):
        DirectorySource().inventory(InputSource(tmp_path / "other.txt", InputSourceKind.FILE))
    directory = tmp_path / "directory"
    directory.mkdir()
    (directory / "nested").mkdir()
    with pytest.raises(ImportSecurityError):
        DirectorySource().inventory(InputSource(directory, InputSourceKind.DIRECTORY))
