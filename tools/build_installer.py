"""Construye el instalador NSIS por usuario desde el ZIP portable verificado."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist"
NSIS_SCRIPT = ROOT / "packaging" / "nsis" / "installer.nsi"
PORTABLE_PREFIX = "GTFS Explorer Portable"
PRODUCT_NAME = "GTFS Explorer Desktop"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_version() -> str:
    for line in (ROOT / "src" / "gtfs_explorer" / "__init__.py").read_text("utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("No se encontró __version__ en gtfs_explorer.")


def _portable_archive(version: str) -> Path:
    return DIST_ROOT / f"GTFS-Explorer-Portable-{version}-win-x64.zip"


def _is_safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    windows_path = PureWindowsPath(name)
    return (
        not path.is_absolute()
        and not windows_path.is_absolute()
        and not windows_path.drive
        and ".." not in path.parts
        and ".." not in windows_path.parts
    )


def _extract_payload(archive_path: Path, destination: Path) -> Path:
    with zipfile.ZipFile(archive_path) as archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        if not files or any(not _is_safe_member(item.filename) for item in files):
            raise RuntimeError("El ZIP portable contiene rutas no seguras o está vacío.")
        prefix = f"{PORTABLE_PREFIX}/"
        if any(not item.filename.startswith(prefix) for item in files):
            raise RuntimeError("El ZIP portable no tiene una raíz de distribución válida.")
        archive.extractall(destination)
    payload = destination / PORTABLE_PREFIX
    if not (payload / "GTFS Explorer.exe").is_file() or not (payload / "portable.flag").is_file():
        raise RuntimeError("El ZIP portable no contiene el ejecutable y portable.flag esperados.")
    # El modo instalado debe emplear LOCALAPPDATA; portable.flag cambiaría esa semántica.
    (payload / "portable.flag").unlink()
    return payload


def _run_makensis(*, executable: str, version: str, payload: Path, output: Path) -> None:
    command = [
        executable,
        f"/DPRODUCT_VERSION={version}",
        f"/DPAYLOAD_DIR={payload}",
        f"/DINSTALLER_OUTPUT={output}",
        str(NSIS_SCRIPT),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def _write_manifest(*, setup: Path, portable: Path, version: str) -> Path:
    manifest = setup.with_suffix(".manifest.json")
    payload = {
        "product": PRODUCT_NAME,
        "version": version,
        "format": "nsis-per-user-v1",
        "installer": {"file": setup.name, "sha256": _sha256(setup), "bytes": setup.stat().st_size},
        "portable_source": {"file": portable.name, "sha256": _sha256(portable)},
        "workspace_policy": "preserved-under-localappdata",
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def build(*, makensis: str = "makensis", dry_run: bool = False) -> Path | None:
    version = _read_version()
    portable = _portable_archive(version)
    if not portable.is_file():
        raise RuntimeError(f"No existe el ZIP portable requerido: {portable}")
    if not NSIS_SCRIPT.is_file():
        raise RuntimeError(f"No existe el script NSIS: {NSIS_SCRIPT}")
    if dry_run:
        return None
    DIST_ROOT.mkdir(exist_ok=True)
    setup = DIST_ROOT / f"GTFS-Explorer-Setup-{version}-win-x64.exe"
    with tempfile.TemporaryDirectory(prefix="gtfs-explorer-nsis-", dir=ROOT / ".tmp") as temporary:
        payload = _extract_payload(portable, Path(temporary))
        _run_makensis(executable=makensis, version=version, payload=payload, output=setup)
    if not setup.is_file():
        raise RuntimeError("NSIS no generó el setup esperado.")
    _write_manifest(setup=setup, portable=portable, version=version)
    setup.with_suffix(".exe.sha256").write_text(
        f"{_sha256(setup)}  {setup.name}\n", encoding="ascii"
    )
    return setup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--makensis", default="makensis", help="Ruta o comando de makensis.")
    parser.add_argument("--dry-run", action="store_true", help="Valida entradas sin invocar NSIS.")
    arguments = parser.parse_args()
    result = build(makensis=arguments.makensis, dry_run=arguments.dry_run)
    if result is not None:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
