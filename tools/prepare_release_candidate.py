"""Verifica los binarios existentes y materializa los metadatos de una RC local.

No recompila, firma ni publica. La RC siempre queda marcada como local hasta
que el responsable autorice expresamente su distribución.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtfs_explorer.product import IDENTITY  # noqa: E402

DIST = ROOT / "dist"
PRODUCT = IDENTITY.name
PORTABLE_PREFIX = "GTFS-Explorer-Portable-"
SETUP_PREFIX = "GTFS-Explorer-Setup-"
REQUIRED_PORTABLE_FILES = (
    "GTFS Explorer.exe",
    "portable.flag",
    "manifest.json",
    "LICENSES/README.md",
    "THIRD_PARTY_NOTICES.html",
    "SBOM.cdx.json",
    "web/map/qt_resources/map_bundle.js",
    "web/map/qt_resources/map_layers.js",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _version() -> str:
    return IDENTITY.version


def _single_artifact(pattern: str) -> Path:
    matches = sorted(DIST.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"Se esperaba un único artefacto {pattern}; encontrados: {len(matches)}")
    return matches[0]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON inválido en {path.name}: se esperaba un objeto.")
    return payload


def _expected_sidecar_hash(path: Path) -> str:
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not sidecar.is_file():
        raise RuntimeError(f"Falta el hash lateral: {sidecar.name}")
    fields = sidecar.read_text(encoding="ascii").strip().split()
    if len(fields) != 2 or fields[1] != path.name:
        raise RuntimeError(f"Formato inválido del hash lateral: {sidecar.name}")
    return fields[0].lower()


def verify(version: str) -> dict[str, Any]:
    portable = _single_artifact(f"{PORTABLE_PREFIX}{version}-win-x64.zip")
    setup = _single_artifact(f"{SETUP_PREFIX}{version}-win-x64.exe")
    portable_hash = _sha256(portable)
    setup_hash = _sha256(setup)
    if _expected_sidecar_hash(portable) != portable_hash:
        raise RuntimeError("El hash lateral del portable no coincide.")
    if _expected_sidecar_hash(setup) != setup_hash:
        raise RuntimeError("El hash lateral del instalador no coincide.")

    setup_manifest = _read_json(setup.with_suffix(".manifest.json"))
    if setup_manifest.get("version") != version:
        raise RuntimeError("La versión del manifiesto del instalador no coincide.")
    installer = setup_manifest.get("installer", {})
    portable_source = setup_manifest.get("portable_source", {})
    if installer.get("file") != setup.name or installer.get("sha256") != setup_hash:
        raise RuntimeError("El manifiesto del instalador no coincide con el setup.")
    if (
        portable_source.get("file") != portable.name
        or portable_source.get("sha256") != portable_hash
    ):
        raise RuntimeError("El manifiesto del instalador no coincide con el portable.")

    with zipfile.ZipFile(portable) as archive:
        invalid = archive.testzip()
        if invalid is not None:
            raise RuntimeError(f"El ZIP portable está dañado en: {invalid}")
        names = set(archive.namelist())
        roots = {name.split("/", maxsplit=1)[0] for name in names if name}
        if roots != {"GTFS Explorer Portable"}:
            raise RuntimeError("El ZIP portable no tiene una única raíz esperada.")
        root = "GTFS Explorer Portable/"
        missing = [relative for relative in REQUIRED_PORTABLE_FILES if root + relative not in names]
        if missing:
            raise RuntimeError("Faltan archivos obligatorios en el portable: " + ", ".join(missing))
        portable_manifest = json.loads(archive.read(root + "manifest.json"))
        sbom = json.loads(archive.read(root + "SBOM.cdx.json"))
    if portable_manifest.get("version") != version:
        raise RuntimeError("La versión del manifiesto interno no coincide.")
    if sbom.get("specVersion") != "1.5":
        raise RuntimeError("El SBOM interno no declara CycloneDX 1.5.")

    return {
        "portable": {
            "file": portable.name,
            "sha256": portable_hash,
            "bytes": portable.stat().st_size,
        },
        "installer": {"file": setup.name, "sha256": setup_hash, "bytes": setup.stat().st_size},
    }


def prepare(version: str, label: str) -> Path:
    artifacts = verify(version)
    candidate = DIST / f"GTFS-Explorer-{version}-{label}"
    candidate.mkdir(parents=True, exist_ok=True)
    hashes = (
        "\n".join(
            f"{artifact['sha256']}  ../{artifact['file']}"
            for artifact in (artifacts["portable"], artifacts["installer"])
        )
        + "\n"
    )
    (candidate / "SHA256SUMS.txt").write_text(hashes, encoding="ascii")
    manifest = {
        "product": PRODUCT,
        "version": version,
        "candidate": label,
        "status": "LOCAL_RC_NOT_APPROVED_FOR_DISTRIBUTION",
        "artifacts": artifacts,
        "validation": {
            "portable_zip_integrity": "passed",
            "portable_required_files": "passed",
            "sidecar_hashes": "passed",
            "installer_manifest": "passed",
            "clean_windows_smoke": "T094 passed; I03 skipped because no N-1 installer exists",
        },
        "publication": "requires explicit authorization from Yeison",
    }
    (candidate / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with zipfile.ZipFile(DIST / artifacts["portable"]["file"]) as archive:
        root = "GTFS Explorer Portable/"
        for filename in ("THIRD_PARTY_NOTICES.html", "SBOM.cdx.json"):
            (candidate / filename).write_bytes(archive.read(root + filename))
    shutil.copy2(ROOT / "CHANGELOG.md", candidate / "CHANGELOG.md")
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="rc1", help="Etiqueta local de la candidata.")
    parser.add_argument("--verify-only", action="store_true", help="Solo valida los artefactos.")
    arguments = parser.parse_args()
    version = _version()
    if arguments.verify_only:
        verify(version)
        print(f"Artefactos {version} verificados correctamente.")
    else:
        print(prepare(version, arguments.label))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
