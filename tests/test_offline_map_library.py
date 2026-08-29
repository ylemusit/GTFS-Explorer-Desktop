from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from gtfs_explorer.infrastructure.maps.offline_library import (
    CoverageStatus,
    OfflineMapCatalogEntry,
    OfflineMapError,
    OfflineMapLibrary,
    ProjectMapCoverage,
    RenderStatus,
    TileType,
    classify_coverage,
    resolve_best_map,
)


def _pmtiles(path: Path, tile_type: int = 1) -> Path:
    header = bytearray(264)
    header[:8] = b"PMTiles\x03"
    header[99] = tile_type
    path.write_bytes(header)
    return path


def test_import_is_global_atomic_and_persists_a_light_index(tmp_path: Path) -> None:
    library = OfflineMapLibrary(tmp_path / "maps")
    source = _pmtiles(tmp_path / "Mallorca.pmtiles")

    package = library.import_file(source, package_id="mallorca", version="1")

    assert source.exists()
    assert (library.package_root(package) / "map.pmtiles").is_file()
    assert library.index_path.is_file()
    assert library.installed_maps() == (package,)
    assert not list(library.root.glob("*.part"))
    assert package.render_status is RenderStatus.UNSUPPORTED_STYLE


def test_invalid_or_duplicate_map_is_never_published(tmp_path: Path) -> None:
    library = OfflineMapLibrary(tmp_path / "maps")
    invalid = tmp_path / "invalid.pmtiles"
    invalid.write_bytes(b"bad")
    with pytest.raises(OfflineMapError):
        library.import_file(invalid)
    valid = _pmtiles(tmp_path / "one.pmtiles")
    library.import_file(valid, package_id="one", version="1")
    with pytest.raises(OfflineMapError, match="mismo id"):
        library.import_file(valid, package_id="one", version="1")
    assert len(library.installed_maps()) == 1


def test_coverage_and_deterministic_selection() -> None:
    from datetime import UTC, datetime

    from gtfs_explorer.infrastructure.maps.offline_library import OfflineMapPackage

    now = datetime.now(UTC).isoformat()
    large = OfflineMapPackage(
        "large",
        "Large",
        "l.pmtiles",
        (-10, 40, 10, 50),
        0,
        14,
        100,
        None,
        None,
        None,
        None,
        None,
        None,
        now,
        TileType.VECTOR,
        RenderStatus.RENDERABLE_BASEMAP,
        "fixture",
    )
    detail = OfflineMapPackage(
        "detail",
        "Detail",
        "d.pmtiles",
        (-6, 42, -5, 44),
        0,
        15,
        200,
        None,
        None,
        None,
        None,
        None,
        None,
        now,
        TileType.VECTOR,
        RenderStatus.RENDERABLE_BASEMAP,
        "fixture",
    )
    coverage = ProjectMapCoverage((-5.8, 43.1, -5.7, 43.2), "shapes")
    assert classify_coverage(coverage, detail) is CoverageStatus.COVERED
    assert (
        classify_coverage(ProjectMapCoverage((-8, 43, -5.5, 44)), detail)
        is CoverageStatus.PARTIALLY_COVERED
    )
    assert resolve_best_map(coverage, (large, detail)) == detail


class _Response(io.BytesIO):
    headers = {"Content-Length": "264"}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_download_mock_streams_checks_and_installs(tmp_path: Path) -> None:
    payload = bytes(bytearray(b"PMTiles\x03" + bytes(256)))
    catalog = OfflineMapCatalogEntry(
        "mock",
        "Mock",
        None,
        None,
        None,
        len(payload),
        "https://maps.invalid/mock",
        hashlib.sha256(payload).hexdigest(),
        "sha256",
        None,
        None,
        "fixture",
        "1",
    )
    progress: list[int] = []
    package = OfflineMapLibrary(tmp_path / "maps").download(
        catalog,
        opener=lambda _url: _Response(payload),
        on_progress=lambda done, _total: progress.append(done),
    )
    assert package.package_id == "mock"
    assert progress == [len(payload)]


def test_valid_vector_without_style_is_not_a_basemap_or_recommendation(tmp_path: Path) -> None:
    library = OfflineMapLibrary(tmp_path / "maps")
    item = library.import_file(_pmtiles(tmp_path / "vector.pmtiles", 1))
    assert item.tile_type is TileType.VECTOR
    assert item.render_status is RenderStatus.UNSUPPORTED_STYLE
    assert resolve_best_map(ProjectMapCoverage((-1, -1, 1, 1)), (item,)) is None


def test_raster_pmtiles_gets_a_local_renderable_style(tmp_path: Path) -> None:
    library = OfflineMapLibrary(tmp_path / "maps")
    item = library.import_file(_pmtiles(tmp_path / "raster.pmtiles", 2))
    assert item.tile_type is TileType.RASTER
    assert item.is_renderable
    assert (library.package_root(item) / "style.json").is_file()
    assert "C:" not in library.index_path.read_text(encoding="utf-8")
