"""Pruebas focales de intercambio KML/KMZ seguro del editor 0.2.0."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from gtfs_explorer.domain.changesets import WorkingCopy
from gtfs_explorer.domain.exporting import ExportError
from gtfs_explorer.infrastructure.exporting.kml import (
    KmlClassification,
    KmlProfile,
    KmlSecurityError,
    SafeKmlReader,
    WorkingCopyKmlExporter,
)


def _working_copy() -> WorkingCopy:
    working_copy = WorkingCopy(
        {
            ("gtfs_routes", "R1"): {"route_id": "R1", "route_short_name": "1"},
            ("gtfs_trips", "T1"): {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "W1",
                "shape_id": "SH1",
            },
            ("gtfs_stop_times", "1"): {"trip_id": "T1", "stop_id": "S1"},
            ("gtfs_stops", "S1"): {
                "stop_id": "S1",
                "stop_name": "Centro",
                "stop_lat": 40.0,
                "stop_lon": -3.0,
            },
            ("gtfs_shapes", "1"): {
                "shape_id": "SH1",
                "shape_pt_sequence": 1,
                "shape_pt_lat": 40.0,
                "shape_pt_lon": -3.0,
            },
            ("gtfs_shapes", "2"): {
                "shape_id": "SH1",
                "shape_pt_sequence": 2,
                "shape_pt_lat": 40.1,
                "shape_pt_lon": -3.1,
            },
        }
    )
    working_copy.promote_revision("revision-1")
    return working_copy


def test_working_copy_kml_and_kmz_round_trip_metadata(tmp_path: Path) -> None:
    working_copy = _working_copy()
    exporter = WorkingCopyKmlExporter()
    kml = tmp_path / "revision.kml"
    exporter.write(
        kml,
        working_copy,
        revision_id="revision-1",
        confirmed=True,
        profile=KmlProfile.GOOGLE_EARTH,
    )
    preview = SafeKmlReader().inspect(kml)
    assert preview.classification is KmlClassification.GTFS_EXPLORER_KML
    assert preview.placemark_count == 2
    assert preview.point_count == 1
    assert preview.line_string_count == 1

    kmz = tmp_path / "revision.kmz"
    exporter.write(kmz, working_copy, revision_id="revision-1", confirmed=True)
    assert kmz.is_file() and kmz.stat().st_size > 0
    with ZipFile(kmz) as archive:
        assert archive.namelist() == ["doc.kml"]
        assert b"<kml" in archive.read("doc.kml")
    assert SafeKmlReader().inspect(kmz).classification is KmlClassification.GTFS_EXPLORER_KML


def test_kml_export_requires_confirmed_revision(tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="borrador"):
        WorkingCopyKmlExporter().write(
            tmp_path / "draft.kml",
            _working_copy(),
            revision_id="draft",
            confirmed=False,
        )


def test_kml_reader_rejects_dangerous_xml_and_zip_paths(tmp_path: Path) -> None:
    dangerous = tmp_path / "dangerous.kml"
    dangerous.write_bytes(
        b'<!DOCTYPE kml [<!ENTITY xxe SYSTEM "file:///secret">]>'
        b'<kml xmlns="http://www.opengis.net/kml/2.2"></kml>'
    )
    with pytest.raises(KmlSecurityError):
        SafeKmlReader().inspect(dangerous)

    slip = tmp_path / "slip.kmz"
    with ZipFile(slip, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("../doc.kml", b"<kml/>")
    with pytest.raises(KmlSecurityError):
        SafeKmlReader().inspect(slip)
