"""Matriz de seguridad del lector ZIP confinado."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from gtfs_explorer.domain.errors import ImportCancelled, ImportSecurityError
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.infrastructure.importing.zip_source import ZipLimits, ZipSource


def _archive(path: Path, entries: dict[str, bytes]) -> InputSource:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, contents in entries.items():
            archive.writestr(name, contents)
    return InputSource(path, InputSourceKind.ARCHIVE)


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "file.txt:stream", "CON.txt"])
def test_zip_rejects_unsafe_names(tmp_path: Path, name: str) -> None:
    source = _archive(tmp_path / "unsafe.zip", {name: b"x"})
    with pytest.raises(ImportSecurityError):
        ZipSource().inventory(source)


def test_zip_rejects_logical_collisions_and_limits(tmp_path: Path) -> None:
    collision = _archive(tmp_path / "collision.zip", {"Stops.TXT": b"a", "stops.txt": b"b"})
    with pytest.raises(ImportSecurityError):
        ZipSource().inventory(collision)

    source = _archive(tmp_path / "many.zip", {"one.txt": b"x", "two.txt": b"y"})
    with pytest.raises(ImportSecurityError):
        ZipSource(ZipLimits(max_entries=1)).inventory(source)


def test_zip_extracts_valid_content_only_inside_temporary_directory(tmp_path: Path) -> None:
    source = _archive(tmp_path / "valid.zip", {"stops.txt": b"stop_id\nS1\n"})
    destination = tmp_path / "temporary"

    manifest = ZipSource().extract(source, destination, has_free_space=lambda _required: True)

    assert (destination / "stops.txt").read_bytes() == b"stop_id\nS1\n"
    assert manifest.entries[0].original_name == "stops.txt"


def test_zip_requires_space_and_honours_cancellation(tmp_path: Path) -> None:
    source = _archive(tmp_path / "valid.zip", {"stops.txt": b"content"})
    reader = ZipSource()
    with pytest.raises(ImportSecurityError):
        reader.extract(source, tmp_path / "no-space", has_free_space=lambda _required: False)
    with pytest.raises(ImportCancelled):
        reader.extract(
            source,
            tmp_path / "cancelled",
            has_free_space=lambda _required: True,
            is_cancelled=lambda: True,
        )
