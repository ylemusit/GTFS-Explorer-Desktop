from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from gtfs_explorer.domain.exporting import (
    ExportCancelled,
    ExportDestinationError,
    ExportDestinationExistsError,
    ExportError,
)
from gtfs_explorer.infrastructure.exporting.atomic_output import AtomicOutputWriter


def test_writes_unicode_artifact_and_deterministic_sidecar_manifest(tmp_path: Path) -> None:
    destination = tmp_path / "salida ñ.json"

    manifest = AtomicOutputWriter().write(destination, (b"uno", b"dos"))

    assert destination.read_bytes() == b"unodos"
    assert manifest.sha256 == hashlib.sha256(b"unodos").hexdigest()
    assert manifest.artifact_name == "salida ñ.json"
    assert json.loads((tmp_path / "salida ñ.json.manifest.json").read_text(encoding="utf-8")) == {
        "artifact_name": "salida ñ.json",
        "schema_version": 1,
        "sha256": manifest.sha256,
        "size_bytes": 6,
    }


def test_existing_destination_requires_explicit_overwrite(tmp_path: Path) -> None:
    destination = tmp_path / "export.json"
    destination.write_bytes(b"anterior")
    writer = AtomicOutputWriter()

    with pytest.raises(ExportDestinationExistsError):
        writer.write(destination, (b"nuevo",))

    assert destination.read_bytes() == b"anterior"
    writer.write(destination, (b"nuevo",), overwrite=True)
    assert destination.read_bytes() == b"nuevo"


def test_cancelled_or_full_disk_export_leaves_no_final_or_temporary_files(tmp_path: Path) -> None:
    destination = tmp_path / "export.json"
    writer = AtomicOutputWriter()

    with pytest.raises(ExportCancelled):
        writer.write(destination, (b"first", b"second"), is_cancelled=lambda: True)
    assert not list(tmp_path.iterdir())

    full_disk_writer = AtomicOutputWriter(has_free_space=lambda _directory, _bytes: False)
    with pytest.raises(ExportError):
        full_disk_writer.write(destination, (b"first",))
    assert not list(tmp_path.iterdir())


def test_rejects_destination_inside_a_protected_internal_root(tmp_path: Path) -> None:
    protected = tmp_path / "workspace"
    protected.mkdir()

    with pytest.raises(ExportDestinationError):
        AtomicOutputWriter(protected_roots=(protected,)).write(protected / "result.json", (b"x",))
