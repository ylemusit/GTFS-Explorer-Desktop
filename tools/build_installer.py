"""Construye el instalador NSIS por usuario desde el ZIP portable verificado."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtfs_explorer.product import IDENTITY, windows_file_version  # noqa: E402

DIST_ROOT = ROOT / "dist"
NSIS_SCRIPT = ROOT / "packaging" / "nsis" / "installer.nsi"
PORTABLE_PREFIX = IDENTITY.portable_directory_name
LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHORT_ARTIFACT_LABEL_PREFIXES = ("P2A-", "GTFS023-")
TOOL_NOT_AVAILABLE = "SKIPPED / TOOL_NOT_AVAILABLE"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_version() -> str:
    return IDENTITY.version


def _validate_label(label: str | None) -> str | None:
    if label is not None and not LABEL_PATTERN.fullmatch(label):
        raise ValueError("La etiqueta solo puede contener letras, números, '.', '_' o '-'.")
    return label


def _artifact_name(prefix: str, version: str, label: str | None, suffix: str) -> str:
    if label and label.startswith(SHORT_ARTIFACT_LABEL_PREFIXES):
        return f"{prefix}-{label}-win-x64{suffix}"
    label_part = f"-{label}" if label else ""
    return f"{prefix}-{version}{label_part}-win-x64{suffix}"


def _portable_archive(version: str, output_dir: Path = DIST_ROOT, label: str | None = None) -> Path:
    return output_dir / _artifact_name("GTFS-Explorer-Portable", version, label, ".zip")


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
    if (
        not (payload / IDENTITY.executable_name).is_file()
        or not (payload / "portable.flag").is_file()
    ):
        raise RuntimeError("El ZIP portable no contiene el ejecutable y portable.flag esperados.")
    # El modo instalado debe emplear LOCALAPPDATA; portable.flag cambiaría esa semántica.
    (payload / "portable.flag").unlink()
    return payload


def _run_makensis(*, executable: str, version: str, payload: Path, output: Path) -> None:
    command = [
        executable,
        f"/DPRODUCT_VERSION={version}",
        f"/DPRODUCT_FILE_VERSION={IDENTITY.windows_file_version}",
        f"/DPRODUCT_NAME={IDENTITY.name}",
        f"/DPRODUCT_PUBLISHER={IDENTITY.author}",
        f"/DPRODUCT_DESCRIPTION={IDENTITY.file_description}",
        f"/DPRODUCT_EDITION={IDENTITY.edition}",
        f"/DPRODUCT_COPYRIGHT_YEAR={IDENTITY.copyright_year}",
        f"/DPRODUCT_RIGHTS_NOTICE={IDENTITY.rights_notice}",
        f"/DPRODUCT_EXECUTABLE={IDENTITY.executable_name}",
        f"/DPRODUCT_INSTALL_DIRECTORY={IDENTITY.install_directory_name}",
        f"/DPRODUCT_START_MENU_DIRECTORY={IDENTITY.start_menu_directory_name}",
        f"/DPRODUCT_SHORTCUT_NAME={IDENTITY.shortcut_name}",
        f"/DPAYLOAD_DIR={payload}",
        f"/DINSTALLER_OUTPUT={output}",
        str(NSIS_SCRIPT),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def _resolve_makensis(executable: str) -> str | None:
    """Resuelve un binario explícito o uno disponible en ``PATH``."""
    candidate = Path(executable)
    if candidate.is_file():
        return str(candidate.resolve())
    return shutil.which(executable)


def _write_manifest(*, setup: Path, portable: Path, version: str, label: str | None = None) -> Path:
    manifest = setup.with_suffix(".manifest.json")
    payload = {
        "product": IDENTITY.name,
        "version": version,
        "file_version": windows_file_version(version),
        "build_label": label,
        "format": "nsis-per-user-v1",
        "installer": {"file": setup.name, "sha256": _sha256(setup), "bytes": setup.stat().st_size},
        "portable_source": {"file": portable.name, "sha256": _sha256(portable)},
        "workspace_policy": "preserved-under-localappdata",
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def build(
    *,
    makensis: str = "makensis",
    dry_run: bool = False,
    output_dir: Path | None = None,
    label: str | None = None,
) -> Path | None:
    version = _read_version()
    label = _validate_label(label)
    destination_root = (output_dir or DIST_ROOT).resolve()
    portable = _portable_archive(version, destination_root, label)
    if not portable.is_file():
        raise RuntimeError(f"No existe el ZIP portable requerido: {portable}")
    if not NSIS_SCRIPT.is_file():
        raise RuntimeError(f"No existe el script NSIS: {NSIS_SCRIPT}")
    if dry_run:
        return None
    resolved_makensis = _resolve_makensis(makensis)
    if resolved_makensis is None:
        raise RuntimeError(f"{TOOL_NOT_AVAILABLE}: no se encontró makensis.")
    destination_root.mkdir(parents=True, exist_ok=True)
    setup = destination_root / _artifact_name("GTFS-Explorer-Setup", version, label, ".exe")
    with tempfile.TemporaryDirectory(prefix="gtfs-explorer-nsis-", dir=ROOT / ".tmp") as temporary:
        payload = _extract_payload(portable, Path(temporary))
        _run_makensis(executable=resolved_makensis, version=version, payload=payload, output=setup)
    if not setup.is_file():
        raise RuntimeError("NSIS no generó el setup esperado.")
    _write_manifest(setup=setup, portable=portable, version=version, label=label)
    setup.with_suffix(".exe.sha256").write_text(
        f"{_sha256(setup)}  {setup.name}\n", encoding="ascii"
    )
    return setup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--makensis", default="makensis", help="Ruta o comando de makensis.")
    parser.add_argument(
        "--check-makensis",
        action="store_true",
        help="Comprueba la disponibilidad sin compilar ni crear artefactos.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Valida entradas sin invocar NSIS.")
    parser.add_argument("--output-dir", type=Path, help="Directorio de salida; por defecto, dist/.")
    parser.add_argument("--label", help="Etiqueta aislada añadida al nombre del artefacto.")
    arguments = parser.parse_args()
    if arguments.check_makensis:
        resolved = _resolve_makensis(arguments.makensis)
        print(f"AVAILABLE / {resolved}" if resolved else TOOL_NOT_AVAILABLE)
        return 0
    result = build(
        makensis=arguments.makensis,
        dry_run=arguments.dry_run,
        output_dir=arguments.output_dir,
        label=arguments.label,
    )
    if result is not None:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
