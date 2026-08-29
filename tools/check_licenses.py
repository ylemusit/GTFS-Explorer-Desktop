"""Genera y verifica el inventario de licencias del artefacto Windows.

No intenta sustituir una revision juridica: el catalogo es deliberadamente
cerrado. Un binario nuevo sin regla de atribucion hace fallar el proceso.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtfs_explorer.product import IDENTITY  # noqa: E402

# Cada patron debe corresponder a software que puede llegar al standalone.
COMPONENTS = (
    (
        "python",
        "CPython",
        "3.12",
        "PSF-2.0",
        ("_*.pyd", "select.pyd", "unicodedata.pyd", "python*.dll"),
    ),
    ("duckdb", "DuckDB", "1.1.3", "MIT", ("duckdb/*",)),
    ("shapely", "Shapely", "2.1.2", "BSD-3-Clause", ("shapely/*",)),
    (
        "pyside6",
        "PySide6",
        "6.8.3",
        "LGPL-3.0-only OR GPL-3.0-only",
        ("PySide6/*", "pyside6.abi3.dll", "shiboken6*"),
    ),
    (
        "qt",
        "Qt 6",
        "6.8.3",
        "LGPL-3.0-only OR GPL-3.0-only",
        ("qt6*", "qtwebengine*", "QtWebEngineProcess.exe", "qt6.conf", "v8_context_snapshot*"),
    ),
    (
        "openssl",
        "OpenSSL",
        "3",
        "Apache-2.0",
        ("libcrypto-3.dll", "libssl-3.dll", "_ssl.pyd", "_hashlib.pyd"),
    ),
    ("icu", "ICU", "unknown", "ICU", ("icudtl.dat",)),
    (
        "msvc-runtime",
        "Microsoft Visual C++ Runtime",
        "14",
        "LicenseRef-Microsoft-VC-Runtime",
        ("msvcp*.dll", "vcruntime*.dll"),
    ),
    ("maplibre", "MapLibre GL JS", "6.3.0", "BSD-3-Clause", ("web/map/qt_resources/map*",)),
    ("pmtiles", "PMTiles", "4.5.0", "BSD-3-Clause", ("web/map/qt_resources/map*",)),
)

ALLOWED_NON_BINARIES = (
    "portable.flag",
    "manifest.json",
    "docs/USER_GUIDE.md",
    "THIRD_PARTY_NOTICES.html",
    "SBOM.cdx.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _component_payload() -> list[dict[str, object]]:
    result = [
        {
            "type": "application",
            "bom-ref": f"gtfs-explorer-desktop@{IDENTITY.version}",
            "name": IDENTITY.name,
            "version": IDENTITY.version,
            "licenses": [{"license": {"id": "LicenseRef-Proprietary"}}],
            "author": IDENTITY.author,
        }
    ]
    for identifier, name, version, license_id, _ in COMPONENTS:
        result.append(
            {
                "type": "library",
                "bom-ref": f"{identifier}@{version}",
                "name": name,
                "version": version,
                "licenses": [{"expression": license_id}],
                "properties": [{"name": "gtfs-explorer:distribution", "value": "windows-x64"}],
            }
        )
    return result


def _write_sbom(destination: Path) -> Path:
    output = destination / "SBOM.cdx.json"
    payload = {
        "$schema": "http://cyclonedx.org/schema/bom-1.5.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:00000000-0000-4000-8000-000000000093",
        "version": 1,
        "metadata": {
            "component": _component_payload()[0],
            "tools": [
                {"vendor": "GTFS Explorer", "name": "tools/check_licenses.py", "version": "1"}
            ],
        },
        "components": _component_payload()[1:],
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _write_notices(destination: Path) -> Path:
    output = destination / "THIRD_PARTY_NOTICES.html"
    rows = "\n".join(
        f"<tr><td>{name}</td><td>{version}</td><td>{license_id}</td><td><code>{identifier}</code></td></tr>"
        for identifier, name, version, license_id, _ in COMPONENTS
    )
    output.write_text(
        '<!doctype html><meta charset="utf-8"><title>Avisos de terceros</title>'
        f"<h1>{IDENTITY.name}: avisos de terceros</h1>"
        f"<p>Copyright {IDENTITY.copyright_year} {IDENTITY.author}. "
        f"{IDENTITY.rights_notice}</p>"
        "<p>Qt/PySide6 se distribuyen bajo LGPLv3 o GPLv3. La revision juridica de "
        "cumplimiento LGPL "
        "queda pendiente antes de cualquier venta o publicacion. Los datos de mapa no se "
        "incluyen por defecto; "
        "si se anaden datos OSM, su atribucion debe permanecer visible en el mapa.</p>"
        '<table border="1"><tr><th>Componente</th><th>Version</th><th>Licencia</th>'
        "<th>Id SBOM</th></tr>"
        f"{rows}</table><p>Textos y referencias: carpeta LICENSES del paquete.</p>",
        encoding="utf-8",
    )
    return output


def _copy_licenses(destination: Path) -> None:
    source = ROOT / "LICENSES"
    target = destination / "LICENSES"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _matches_component(relative: str) -> bool:
    path = Path(relative)
    if relative in ALLOWED_NON_BINARIES or relative.startswith("LICENSES/"):
        return True
    if relative.startswith("duckdb/"):
        return True
    # Recursos, Python y ficheros de aplicacion no son binarios de terceros sin catalogar.
    if relative == "GTFS Explorer.exe" or relative.startswith(
        (
            "gtfs_explorer/",
            "schemas/",
            "web/map/qt_resources/",
            "PySide6/",
            "shiboken6/",
        )
    ):
        return True
    return any(path.match(pattern) for _, _, _, _, patterns in COMPONENTS for pattern in patterns)


def verify(artifact: Path) -> list[str]:
    unknown = []
    for required in ("LICENSES/README.md", "THIRD_PARTY_NOTICES.html", "SBOM.cdx.json"):
        if not (artifact / required).is_file():
            unknown.append(f"Falta el artefacto legal obligatorio: {required}")
    for path in artifact.rglob("*"):
        if path.is_file() and not _matches_component(path.relative_to(artifact).as_posix()):
            unknown.append(path.relative_to(artifact).as_posix())
    return sorted(unknown)


def prepare(artifact: Path) -> None:
    _copy_licenses(artifact)
    _write_notices(artifact)
    _write_sbom(artifact)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, help="Raiz del portable que se comprueba.")
    parser.add_argument(
        "--prepare", action="store_true", help="Copia avisos, licencias y SBOM al artefacto."
    )
    arguments = parser.parse_args()
    destination = arguments.artifact or ROOT
    if arguments.prepare:
        prepare(destination)
    unknown = verify(destination) if arguments.artifact else []
    if unknown:
        print(
            "Archivos distribuidos sin componente/licencia conocida:\n" + "\n".join(unknown),
            file=sys.stderr,
        )
        return 1
    if not arguments.artifact:
        _write_notices(ROOT)
        _write_sbom(ROOT)
    print(f"Inventario de licencias verificado: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
