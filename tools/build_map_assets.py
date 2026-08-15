"""Construye recursos web del mapa de forma bloqueada y verificable."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_ROOT = ROOT / "web" / "map"
DIST = MAP_ROOT / "dist"
QT_RESOURCES = MAP_ROOT / "qt_resources"
LICENSES = ROOT / "LICENSES"
ASSETS = ("map_bundle.js", "map_worker.mjs", "maplibre-gl-shared.mjs", "maplibre-gl.css")
LOCAL_SCRIPTS = {
    ROOT / "src" / "gtfs_explorer" / "presentation" / "map_bridge" / "map_bridge.js": (
        "map_bridge.js"
    ),
    ROOT / "src" / "gtfs_explorer" / "presentation" / "desktop" / "map" / "map_layers.js": (
        "map_layers.js"
    ),
}
URL = re.compile(
    r"https?://[^\s\"'`<>]+|//(?:[a-z0-9-]+\.)+[a-z]{2,}[^\s\"'`<>]*",
    re.IGNORECASE,
)
ALLOWED_DOCUMENTATION_URLS = {
    "http://www.w3.org/2000/svg",
    "https://github.com/mapbox/mapbox-gl-js/issues/2907",
    "https://github.com/maplibre/maplibre-gl-js/blob/v6.3.0/LICENSE.txt",
    "https://github.com/protomaps/PMTiles/tree/main/js",
    "https://maplibre.org/",
    "https://wiki.openstreetmap.org/wiki/This_map_requires_WebGL",
}


def _run(command: list[str]) -> str:
    result = subprocess.run(command, cwd=MAP_ROOT, text=True, capture_output=True)
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Comando fallido ({' '.join(command)}): {details}")
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def _assert_no_remote_references() -> None:
    checked = [MAP_ROOT / "src" / "app.js", *[DIST / asset for asset in ASSETS]]
    for path in checked:
        urls = set(URL.findall(path.read_text(encoding="utf-8")))
        unexpected = urls - ALLOWED_DOCUMENTATION_URLS
        if unexpected:
            formatted = ", ".join(sorted(unexpected))
            raise RuntimeError(
                f"Referencia remota o CDN prohibida en {path.relative_to(ROOT)}: {formatted}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="prohíbe descargar paquetes npm")
    args = parser.parse_args()

    npm_ci = ["npm.cmd", "ci"]
    if args.offline:
        npm_ci.append("--offline")
    _run(npm_ci)
    _run(["npm.cmd", "run", "build"])
    _assert_no_remote_references()

    QT_RESOURCES.mkdir(exist_ok=True)
    for asset in ASSETS:
        shutil.copy2(DIST / asset, QT_RESOURCES / asset)
    for source, destination in LOCAL_SCRIPTS.items():
        shutil.copy2(source, QT_RESOURCES / destination)
    LICENSES.mkdir(exist_ok=True)
    shutil.copy2(
        MAP_ROOT / "node_modules" / "maplibre-gl" / "LICENSE.txt",
        LICENSES / "maplibre-gl-6.3.0.txt",
    )

    manifest = {
        "lock_sha256": _sha256(MAP_ROOT / "package-lock.json"),
        "node": _run(["node", "--version"]),
        "npm": _run(["npm.cmd", "--version"]),
        "assets": {asset: _sha256(QT_RESOURCES / asset) for asset in ASSETS},
    }
    (QT_RESOURCES / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
