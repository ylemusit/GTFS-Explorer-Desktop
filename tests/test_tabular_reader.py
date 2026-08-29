"""Pruebas del lector tabular que preserva los valores textuales GTFS."""

from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_explorer.domain.errors import TabularReadError
from gtfs_explorer.infrastructure.importing.tabular_reader import (
    CompatibleTabularFormat,
    TabularReader,
)


def test_strict_gtfs_preserves_textual_rfc_csv_values(tmp_path: Path) -> None:
    path = tmp_path / "stop_times.txt"
    path.write_bytes(
        (
            "\ufefftrip_id,arrival_time,stop_headsign\r\n"
            '001,25:10:00,"Parada, Norte"\r\n'
            '002,26:00:00,"Dos\r\nLíneas",columna-extra\r\n'
        ).encode()
    )
    parsed = TabularReader().read_gtfs(path)
    assert parsed.header == ("trip_id", "arrival_time", "stop_headsign")
    assert parsed.rows[0].values == ("001", "25:10:00", "Parada, Norte")
    assert parsed.rows[1].number == 3
    assert parsed.rows[1].values == ("002", "26:00:00", "Dos\r\nLíneas", "columna-extra")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_source_row_is_physical_record_start_and_preserves_blank_lines(
    newline: str, tmp_path: Path
) -> None:
    path = tmp_path / "stops.txt"
    path.write_bytes(
        (
            "\ufeffid,name"
            + newline
            + newline
            + "A,Alpha"
            + newline
            + newline
            + newline
            + "B,Beta"
            + newline
        ).encode()
    )

    parsed = TabularReader().read_gtfs(path)

    assert [(row.number, row.values) for row in parsed.rows] == [
        (2, ()),
        (3, ("A", "Alpha")),
        (4, ()),
        (5, ()),
        (6, ("B", "Beta")),
    ]


def test_strict_rejects_invalid_encoding_and_compatible_requires_confirmation(
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"id\n\xff\n")
    with pytest.raises(TabularReadError, match="Fila 2"):
        TabularReader().read_gtfs(invalid)
    csv_path = tmp_path / "partial.csv"
    csv_path.write_text("id;value\n001;ok\n", encoding="latin-1")
    with pytest.raises(TabularReadError, match="Fila 1"):
        TabularReader().read_compatible(
            csv_path, encoding="latin-1", delimiter=";", confirmed=False
        )
    assert TabularReader().read_compatible(
        csv_path, encoding="latin-1", delimiter=";", confirmed=True
    ).rows[0].values == ("001", "ok")


def test_compatible_detection_is_a_proposal_that_requires_confirmation(tmp_path: Path) -> None:
    path = tmp_path / "partial.csv"
    path.write_text("id;description\n001;compatible\n", encoding="utf-8")

    detected = TabularReader().detect_compatible(path)

    assert detected == CompatibleTabularFormat(encoding="utf-8", delimiter=";")
    assert TabularReader().read_compatible(
        path,
        encoding=detected.encoding,
        delimiter=detected.delimiter,
        confirmed=True,
    ).rows[0].values == ("001", "compatible")


@pytest.mark.parametrize(
    ("contents", "expected_row"),
    [
        (b"id\n\xff\n", 2),
        (b'id\n"unterminated\n', 2),
    ],
)
def test_defective_files_report_the_physical_row(
    contents: bytes, expected_row: int, tmp_path: Path
) -> None:
    path = tmp_path / "defective.txt"
    path.write_bytes(contents)

    with pytest.raises(TabularReadError, match=rf"Fila {expected_row}"):
        TabularReader().read_gtfs(path)


def test_configurable_field_limit_reports_the_row(tmp_path: Path) -> None:
    path = tmp_path / "large.txt"
    path.write_text("id\n12345\n", encoding="utf-8")

    with pytest.raises(TabularReadError, match="Fila 2: field larger than field limit \(4\)"):
        TabularReader(maximum_field_size=4).read_gtfs(path)
