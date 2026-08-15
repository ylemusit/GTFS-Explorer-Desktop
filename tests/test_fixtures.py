"""Pruebas de reproducibilidad de los fixtures GTFS ficticios."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile


def _load_builder() -> object:
    builder_path = Path(__file__).parent / "fixtures" / "build_fixtures.py"
    specification = importlib.util.spec_from_file_location("build_fixtures", builder_path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fixtures_are_reproducible_and_openable() -> None:
    builder = _load_builder()
    specifications = Path(__file__).parent / "fixtures" / "specs"
    generated = Path(__file__).parent / "fixtures" / "generated" / "pytest"
    first_output = generated / "first"
    second_output = generated / "second"

    builder.build_fixtures(specifications, first_output)
    builder.build_fixtures(specifications, second_output)

    first_paths = sorted(path.name for path in first_output.iterdir())
    assert first_paths == sorted(path.name for path in second_output.iterdir())
    for name in first_paths:
        assert _sha256(first_output / name) == _sha256(second_output / name)

    valid_manifest = json.loads(
        (first_output / "valid_core.manifest.json").read_text(encoding="utf-8")
    )
    assert valid_manifest["fictitious"] is True
    with ZipFile(first_output / "valid_core.zip") as archive:
        assert archive.namelist() == [
            "agency.txt",
            "calendar.txt",
            "routes.txt",
            "stop_times.txt",
            "stops.txt",
            "trips.txt",
        ]
        assert {entry.date_time for entry in archive.infolist()} == {(2020, 1, 1, 0, 0, 0)}
