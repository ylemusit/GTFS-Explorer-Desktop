from pathlib import Path

import pytest

from gtfs_explorer.presentation.desktop.exporter import (
    EXPORT_BASENAME_MAX_LENGTH,
    ExportFormat,
    normalize_export_destination,
    suggest_export_filename,
)


@pytest.mark.parametrize(
    ("format_", "suffix"),
    (
        (ExportFormat.JSON, "-json.json"),
        (ExportFormat.GEOJSON, "-geojson.geojson"),
        (ExportFormat.CSV, "-csv-faithful.csv"),
        (ExportFormat.MINI_GTFS, "-mini-gtfs.zip"),
        (ExportFormat.COMPLETE_GTFS, "-complete-gtfs.zip"),
        (ExportFormat.KML, "-kml.kml"),
        (ExportFormat.KMZ, "-kmz.kmz"),
    ),
)
def test_suggested_filename_is_safe_contextual_and_format_specific(
    format_: ExportFormat, suffix: str
) -> None:
    name = suggest_export_filename(
        format_,
        route_ids={"R/Á: 1"},
        trip_ids={"T? 1"},
        service_ids={"S* 1"},
    )

    assert name.endswith(suffix)
    assert Path(name).name == name
    assert not any(character in name for character in '<>:"/\\|?*')
    assert not any(ord(character) < 32 for character in name)
    assert len(name) <= EXPORT_BASENAME_MAX_LENGTH
    assert "Á" in name
    assert "route-R-Á-1" in name
    assert "trip-T-1" in name
    assert "service-S-1" in name


def test_suggested_filename_is_stable_and_has_empty_selection_fallback() -> None:
    first = suggest_export_filename(
        ExportFormat.JSON,
        route_ids=["R2", "R1"],
        trip_ids=["T2", "T1"],
        service_ids=["S2", "S1"],
    )
    second = suggest_export_filename(
        ExportFormat.JSON,
        route_ids=["R1", "R2"],
        trip_ids=["T1", "T2"],
        service_ids=["S1", "S2"],
    )

    assert first == second
    assert "route-R1-R2" in first
    assert "trip-T1-T2" in first
    assert "service-S1-S2" in first
    assert suggest_export_filename(ExportFormat.JSON) == "gtfs-export-selection-json.json"


def test_long_ids_are_bounded_without_random_suffixes() -> None:
    route_id = "R" * 400

    first = suggest_export_filename(ExportFormat.MINI_GTFS, route_ids={route_id})
    second = suggest_export_filename(ExportFormat.MINI_GTFS, route_ids={route_id})

    assert first == second
    assert len(first) <= EXPORT_BASENAME_MAX_LENGTH
    assert first.endswith("-mini-gtfs.zip")


@pytest.mark.parametrize(
    ("format_", "typed_name", "expected_name", "spreadsheet_safe"),
    (
        (ExportFormat.JSON, "salida.json.json", "salida.json", False),
        (ExportFormat.GEOJSON, "salida.json", "salida.geojson", False),
        (ExportFormat.CSV, "rutas-faithful.csv.csv", "rutas-faithful.csv", False),
        (ExportFormat.CSV, "rutas.csv", "rutas-spreadsheet-safe.csv", True),
        (ExportFormat.MINI_GTFS, "subconjunto.zip.zip", "subconjunto.zip", False),
        (ExportFormat.KMZ, "foo.kmz.kmz", "foo.kmz", False),
        (ExportFormat.COMPLETE_GTFS, "foo.zip", "foo.zip", False),
        (ExportFormat.KML, "foo.kml", "foo.kml", False),
    ),
)
def test_destination_normalization_keeps_one_safe_extension(
    format_: ExportFormat, typed_name: str, expected_name: str, spreadsheet_safe: bool
) -> None:
    destination = Path("target") / typed_name

    normalized = normalize_export_destination(format_, destination, spreadsheet_safe)

    assert normalized.parent == destination.parent
    assert normalized.name == expected_name
    assert "/" not in normalized.name and "\\" not in normalized.name


def test_destination_normalization_sanitizes_invalid_unicode_and_length() -> None:
    long_name = "Á" * 400 + ":?.json"

    normalized = normalize_export_destination(ExportFormat.JSON, Path(long_name))

    assert normalized.name.endswith(".json")
    assert len(normalized.name) <= EXPORT_BASENAME_MAX_LENGTH
    assert ":" not in normalized.name and "?" not in normalized.name
    assert "Á" in normalized.name


def test_destination_normalization_handles_empty_and_reserved_names() -> None:
    assert normalize_export_destination(ExportFormat.JSON, Path(".")) == Path(".")
    assert normalize_export_destination(ExportFormat.JSON, Path("CON.json")).name == "id-CON.json"
