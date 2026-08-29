"""Construye el ZIP standalone offline de GTFS Explorer para Windows x64."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtfs_explorer.product import (  # noqa: E402
    IDENTITY,
    windows_file_version,
    windows_product_version,
)

SPEC = ROOT / "packaging" / "portable" / "pysidedeploy.spec"
ENTRYPOINT = ROOT / "packaging" / "portable" / "entrypoint.py"
MAP_ASSETS = ROOT / "web" / "map" / "qt_resources"
USER_GUIDE = ROOT / "docs" / "USER_GUIDE.md"
DIST_ROOT = ROOT / "dist"
PRODUCT_DIRECTORY = IDENTITY.portable_directory_name
LICENSE_CHECK = ROOT / "tools" / "check_licenses.py"
LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_version() -> str:
    return IDENTITY.version


def _windows_metadata_args() -> tuple[str, ...]:
    """Argumentos PE generados desde la identidad canónica del producto."""
    return (
        f"--product-name={IDENTITY.name}",
        f"--company-name={IDENTITY.author}",
        f"--file-version={IDENTITY.windows_file_version}",
        f"--product-version={IDENTITY.windows_product_version}",
        f"--file-description={IDENTITY.file_description}",
        f"--copyright={IDENTITY.copyright_text}",
        f"--output-filename={IDENTITY.executable_name}",
    )


def _render_deploy_spec() -> str:
    """Añade metadata Windows a una copia efímera del spec versionado."""
    rendered: list[str] = []
    found_extra_args = False
    metadata = shlex.join(_windows_metadata_args())
    for line in SPEC.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith("title ="):
            ending = "\n" if line.endswith("\n") else ""
            rendered.append(f"title = {IDENTITY.name}{ending}")
        elif line.startswith("extra_args ="):
            ending = "\n" if line.endswith("\n") else ""
            rendered.append(f"{line.rstrip('\r\n')} {metadata}{ending}")
            found_extra_args = True
        else:
            rendered.append(line)
    if not found_extra_args:
        raise RuntimeError("El spec portable no contiene la opción nuitka.extra_args.")
    return "".join(rendered)


def _validate_label(label: str | None) -> str | None:
    if label is not None and not LABEL_PATTERN.fullmatch(label):
        raise ValueError("La etiqueta solo puede contener letras, números, '.', '_' o '-'.")
    return label


def _artifact_name(prefix: str, version: str, label: str | None, suffix: str) -> str:
    label_part = f"-{label}" if label else ""
    return f"{prefix}-{version}{label_part}-win-x64{suffix}"


def _deployment_directory() -> Path:
    # pyside6-deploy keeps Nuitka's standalone output under the executable
    # stem, independently of the human-readable application title.
    return ROOT / "packaging" / "portable" / "deployment" / "entrypoint.dist"


def _clean_previous_deployment() -> None:
    for path in (
        ROOT / "packaging" / "portable" / "deployment",
        ROOT / "packaging" / "portable" / "GTFS Explorer.dist",
    ):
        if path.exists():
            shutil.rmtree(path)


def _run_deploy(*, dry_run: bool) -> None:
    # pyside6-deploy reescribe su spec con rutas absolutas. Usamos una copia
    # efímera para conservar el spec versionado como contrato reproducible.
    with tempfile.NamedTemporaryFile("w", suffix=".spec", delete=False, encoding="utf-8") as file:
        file.write(_render_deploy_spec())
        temporary_spec = Path(file.name)
    try:
        command = [
            str(ROOT / ".venv" / "Scripts" / "pyside6-deploy.exe"),
            "--config-file",
            str(temporary_spec),
            "--force",
            "--keep-deployment-files",
        ]
        if dry_run:
            command.append("--dry-run")
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
    finally:
        temporary_spec.unlink(missing_ok=True)


def _copy_distribution(destination: Path) -> None:
    source = _deployment_directory()
    if not source.is_dir():
        raise RuntimeError(f"pyside6-deploy no generó el standalone esperado: {source}")
    shutil.copytree(source, destination)
    shutil.copytree(MAP_ASSETS, destination / "web" / "map" / "qt_resources")
    help_document = destination / "docs" / "USER_GUIDE.md"
    help_document.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(USER_GUIDE, help_document)
    (destination / "portable.flag").touch()


def _duckdb_package_directory() -> Path:
    specification = importlib.util.find_spec("duckdb")
    locations = None if specification is None else specification.submodule_search_locations
    if not locations:
        raise RuntimeError("No se encontró el paquete DuckDB del entorno de build.")
    source = Path(next(iter(locations))).resolve()
    if not any(source.glob("duckdb*.pyd")):
        raise RuntimeError(f"DuckDB no contiene su extensión Windows x64: {source}")
    return source


def _copy_external_duckdb(destination: Path, *, source: Path | None = None) -> None:
    """Conserva DuckDB como paquete CPython para evitar compilar su extensión con Nuitka."""
    package_source = source or _duckdb_package_directory()
    if not any(package_source.glob("duckdb*.pyd")):
        raise RuntimeError(f"DuckDB no contiene su extensión Windows x64: {package_source}")
    target = destination / "duckdb"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        package_source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


def _executable(directory: Path) -> Path:
    source = directory / "entrypoint.exe"
    executable = directory / IDENTITY.executable_name
    if source.is_file() and not executable.is_file():
        source.replace(executable)
    if not executable.is_file():
        raise RuntimeError(f"El portable no contiene el ejecutable esperado: {executable}")
    return executable


def _smoke_runtime(directory: Path) -> None:
    executable = _executable(directory)
    result = subprocess.run(
        [str(executable), "--runtime-smoke"],
        cwd=directory,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"El standalone no supera el smoke de imports/runtime: código {result.returncode}."
        )


def _smoke_map_runtime(directory: Path) -> dict[str, object]:
    """Exige que el WebEngine del standalone dibuje píxeles de una ruta sintética."""
    executable = _executable(directory)
    with tempfile.TemporaryDirectory(prefix="gtfs-explorer-map-smoke-") as temporary:
        report = Path(temporary) / "map-runtime-smoke.json"
        result = subprocess.run(
            [
                str(executable),
                "--map-runtime-smoke",
                "--map-runtime-smoke-report",
                str(report),
            ],
            # WebEngine puede crear ``debug.log`` en el cwd. Lo aislamos del
            # artefacto y, de paso, acreditamos que el mapa no depende del cwd.
            cwd=temporary,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            check=False,
            timeout=30,
        )
        # Chromium escribe este diagnóstico junto al ejecutable aunque su cwd
        # sea temporal. No forma parte del producto ni del informe del smoke.
        (directory / "debug.log").unlink(missing_ok=True)
        if result.returncode != 0 or not report.is_file():
            raise RuntimeError(
                "El standalone no supera el smoke gráfico del mapa: "
                f"código {result.returncode}, informe={report.is_file()}."
            )
        evidence = json.loads(report.read_text(encoding="utf-8"))
    if (
        evidence.get("success") is not True
        or evidence.get("bridge_ready") is not True
        or not isinstance(evidence.get("route_blue_pixels"), int)
        or evidence["route_blue_pixels"] < 20
    ):
        raise RuntimeError(f"El smoke gráfico del mapa no aportó evidencia válida: {evidence}")
    print(
        "Map runtime smoke: "
        f"bridge_ready={evidence['bridge_ready']}, "
        f"route_blue_pixels={evidence['route_blue_pixels']}, "
        f"viewport={evidence.get('width')}x{evidence.get('height')}"
    )
    return evidence


def _write_manifest(directory: Path, version: str) -> Path:
    files = [path for path in sorted(directory.rglob("*")) if path.is_file()]
    payload = {
        "product": IDENTITY.name,
        "version": version,
        "file_version": windows_file_version(version),
        "product_version": windows_product_version(version),
        "format": "portable-standalone-v1",
        "files": {
            path.relative_to(directory).as_posix(): {
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in files
        },
    }
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _write_zip(source: Path, destination: Path) -> None:
    fixed_time = datetime.now(timezone.utc).replace(microsecond=0).timetuple()[:6]
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo(f"{PRODUCT_DIRECTORY}/{path.relative_to(source).as_posix()}")
            info.date_time = fixed_time
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def build(
    *, dry_run: bool = False, output_dir: Path | None = None, label: str | None = None
) -> Path | None:
    if not ENTRYPOINT.is_file() or not SPEC.is_file() or not MAP_ASSETS.is_dir():
        raise RuntimeError("Faltan los recursos necesarios para el portable.")
    if dry_run:
        _run_deploy(dry_run=True)
        return None

    version = _read_version()
    label = _validate_label(label)
    destination_root = (output_dir or DIST_ROOT).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    zip_path = destination_root / _artifact_name("GTFS-Explorer-Portable", version, label, ".zip")
    deployment = _deployment_directory()
    _clean_previous_deployment()
    with tempfile.TemporaryDirectory(
        prefix="gtfs-explorer-portable-", dir=ROOT / ".tmp"
    ) as temporary:
        package_root = Path(temporary) / PRODUCT_DIRECTORY
        _run_deploy(dry_run=False)
        _executable(deployment)
        _copy_distribution(package_root)
        _copy_external_duckdb(package_root)
        _smoke_runtime(package_root)
        _smoke_map_runtime(package_root)
        subprocess.run(
            [
                str(ROOT / ".venv" / "Scripts" / "python.exe"),
                str(LICENSE_CHECK),
                "--artifact",
                str(package_root),
                "--prepare",
            ],
            cwd=ROOT,
            check=True,
        )
        _write_manifest(package_root, version)
        _write_zip(package_root, zip_path)
    hash_path = zip_path.with_suffix(".zip.sha256")
    archive_hash = _sha256(zip_path)
    hash_path.write_text(f"{archive_hash}  {zip_path.name}\n", encoding="ascii")
    manifest_path = zip_path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                "product": IDENTITY.name,
                "version": version,
                "file_version": windows_file_version(version),
                "product_version": windows_product_version(version),
                "build_label": label,
                "artifact": {
                    "file": zip_path.name,
                    "sha256": archive_hash,
                    "bytes": zip_path.stat().st_size,
                },
                "format": "portable-build-v1",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Muestra el build sin publicar ZIP.")
    parser.add_argument("--output-dir", type=Path, help="Directorio de salida; por defecto, dist/.")
    parser.add_argument("--label", help="Etiqueta aislada añadida al nombre del artefacto.")
    arguments = parser.parse_args()
    result = build(
        dry_run=arguments.dry_run, output_dir=arguments.output_dir, label=arguments.label
    )
    if result is not None:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
