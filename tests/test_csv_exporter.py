from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from gtfs_explorer.infrastructure.exporting.csv_exporter import (
    CsvExporter,
    CsvExportMode,
    CsvExportOptions,
)


def test_faithful_csv_round_trips_lexemes_and_uses_declared_mode(tmp_path: Path) -> None:
    destination = tmp_path / "stops-faithful.csv"
    CsvExporter().write(
        destination,
        headers=("id", "value"),
        rows=(("001", '=HYPERLINK("x,y")'), ("002", "linea uno\nlinea dos")),
    )

    assert list(csv.reader(io.StringIO(destination.read_text(encoding="utf-8"), newline=""))) == [
        ["id", "value"],
        ["001", '=HYPERLINK("x,y")'],
        ["002", "linea uno\nlinea dos"],
    ]
    manifest = json.loads((tmp_path / "stops-faithful.csv.manifest.json").read_text())
    assert manifest["metadata"] == {
        "csv_delimiter": ",",
        "encoding": "utf-8",
        "formula_neutralization": False,
        "mode": "faithful",
        "utf8_bom": False,
    }


def test_safe_csv_neutralizes_formula_prefixes_and_can_include_bom(tmp_path: Path) -> None:
    destination = tmp_path / "view-spreadsheet-safe.csv"
    CsvExporter().write(
        destination,
        headers=("value",),
        rows=(("=1+1",), ("+sum",), ("-42",), ("@name",), ("texto",)),
        options=CsvExportOptions(CsvExportMode.SPREADSHEET_SAFE, include_utf8_bom=True),
    )

    assert destination.read_bytes().startswith(b"\xef\xbb\xbf")
    assert list(csv.reader(io.StringIO(destination.read_text(encoding="utf-8-sig")))) == [
        ["value"],
        ["'=1+1"],
        ["'+sum"],
        ["'-42"],
        ["'@name"],
        ["texto"],
    ]


def test_csv_rejects_ambiguous_name_or_rows_with_wrong_shape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="terminar"):
        CsvExporter().write(tmp_path / "data.csv", headers=("id",), rows=(("1",),))
    with pytest.raises(ValueError, match="exactamente"):
        CsvExporter().write(tmp_path / "data-faithful.csv", headers=("id", "name"), rows=(("1",),))
