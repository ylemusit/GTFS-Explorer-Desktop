from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from gtfs_explorer.infrastructure.maps.loopback import MapPackageServer
from gtfs_explorer.infrastructure.maps.package import MapPackageError, load_map_package


def _write_package(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "basemap.pmtiles").write_bytes(b"PMTiles\x03" + bytes(256))
    (root / "style.json").write_text(
        json.dumps({"version": 8, "sources": {}, "layers": []}), encoding="utf-8"
    )
    hashes = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("basemap.pmtiles", "style.json")
    }
    (root / "package.json").write_text(
        json.dumps(
            {
                "version": 1,
                "basemap": "basemap.pmtiles",
                "style": "style.json",
                "license": "ODbL-1.0",
                "license_url": "https://opendatacommons.org/licenses/odbl/",
                "attribution": "© OpenStreetMap contributors",
                "bbox": [-5.9, 43.0, -5.7, 43.2],
                "min_zoom": 0,
                "max_zoom": 14,
                "source": {"reference": "Fixture ficticia", "remote": False},
                "pmtiles_version": "pmtiles fixture",
                "sha256": hashes,
            }
        ),
        encoding="utf-8",
    )
    return root


def test_valid_package_opens_from_a_usb_like_unicode_path_and_supports_ranges(
    tmp_path: Path,
) -> None:
    package = load_map_package(_write_package(tmp_path / "USB ñ" / "map-package"))
    with MapPackageServer(package) as server:
        request = Request(
            server.url_for(package.basemap.relative_to(package.root)),
            headers={"Range": "bytes=2-9", "Origin": "null"},
        )
        with urlopen(request, timeout=2) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == "bytes 2-9/264"
            assert response.headers["Access-Control-Allow-Origin"] == "null"
            assert response.read() == b"Tiles\x03" + bytes(2)
        with urlopen(
            server.url_for(package.style.relative_to(package.root)), timeout=2
        ) as response:
            assert response.status == 200
    assert package.attribution == "© OpenStreetMap contributors"


@pytest.mark.parametrize("change", ("license", "hash", "remote_style"))
def test_invalid_packages_fail_closed(change: str, tmp_path: Path) -> None:
    root = _write_package(tmp_path / "map-package")
    manifest_path = root / "package.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if change == "license":
        del payload["license"]
    elif change == "hash":
        payload["sha256"]["basemap.pmtiles"] = "0" * 64
    else:
        (root / "style.json").write_text(
            json.dumps(
                {"version": 8, "sprite": "https://cdn.example/sprite", "sources": {}, "layers": []}
            ),
            encoding="utf-8",
        )
        payload["sha256"]["style.json"] = hashlib.sha256(
            (root / "style.json").read_bytes()
        ).hexdigest()
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MapPackageError):
        load_map_package(root)


def test_corrupt_pmtiles_fails_before_the_loopback_server_starts(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "map-package")
    (root / "basemap.pmtiles").write_bytes(b"not a pmtiles")
    payload = json.loads((root / "package.json").read_text(encoding="utf-8"))
    payload["sha256"]["basemap.pmtiles"] = hashlib.sha256(
        (root / "basemap.pmtiles").read_bytes()
    ).hexdigest()
    (root / "package.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MapPackageError, match="PMTiles"):
        load_map_package(root)
