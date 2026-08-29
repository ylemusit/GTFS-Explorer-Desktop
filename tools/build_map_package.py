"""Crea un paquete PMTiles regional verificable, sin autorizar fuentes por defecto."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse


class BuildError(RuntimeError):
    """La creación del paquete no puede continuar de forma segura."""


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _is_remote(source: str) -> bool:
    return urlparse(source).scheme.casefold() in {"http", "https"}


def _run(command: list[str]) -> None:
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError as error:
        raise BuildError(f"No se puede ejecutar pmtiles: {error}") from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise BuildError(f"pmtiles falló ({' '.join(command)}): {detail}")


def _pmtiles_version(binary: str) -> str:
    for argument in ("version", "--version"):
        try:
            result = subprocess.run([binary, argument], text=True, capture_output=True, check=False)
        except OSError as error:
            raise BuildError(f"No se encuentra el ejecutable pmtiles '{binary}'.") from error
        version = (result.stdout or result.stderr).strip()
        if result.returncode == 0 and version:
            return version
    raise BuildError("pmtiles no devolvió una versión utilizable.")


def _copy_tree(source: Path, destination: Path) -> list[Path]:
    if not source.is_dir():
        raise BuildError(f"No existe el directorio de assets: {source}")
    copied: list[Path] = []
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise BuildError(f"No se admiten enlaces simbólicos en assets: {item}")
        if item.is_file():
            target = destination / item.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            copied.append(target)
    return copied


def _parse_bbox(value: str) -> list[float]:
    try:
        bbox = [float(part) for part in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("bbox debe ser oeste,sur,este,norte.") from error
    if len(bbox) != 4 or not (-180 <= bbox[0] < bbox[2] <= 180 and -90 <= bbox[1] < bbox[3] <= 90):
        raise argparse.ArgumentTypeError("bbox debe ser WGS84: oeste < este y sur < norte.")
    return bbox


def _contains_remote_url(value: object) -> bool:
    if isinstance(value, str):
        return value.casefold().startswith(("http://", "https://", "//"))
    if isinstance(value, dict):
        return any(_contains_remote_url(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_remote_url(item) for item in value)
    return False


def _validate_style(path: Path) -> None:
    try:
        style = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError("style.json no es JSON UTF-8 válido.") from error
    if not isinstance(style, dict) or style.get("version") != 8:
        raise BuildError("style.json debe ser un estilo MapLibre v8.")
    if _contains_remote_url(style):
        raise BuildError("style.json contiene una URL remota o CDN prohibido.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", required=True, help="PMTiles local o URL indicada por el responsable."
    )
    parser.add_argument(
        "--source-reference",
        required=True,
        help="Referencia pública o identificador de licencia; no se serializa la ruta local.",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bbox", required=True, type=_parse_bbox)
    parser.add_argument("--min-zoom", required=True, type=int)
    parser.add_argument("--max-zoom", required=True, type=int)
    parser.add_argument("--style", required=True, type=Path)
    parser.add_argument("--tileset-profile", choices=("vector", "raster"), default="vector")
    parser.add_argument(
        "--assets", type=Path, help="Directorio opcional de assets locales del estilo."
    )
    parser.add_argument("--license", required=True, dest="license_name")
    parser.add_argument("--license-url", required=True)
    parser.add_argument("--attribution", required=True)
    parser.add_argument("--confirm-source-authorized", action="store_true")
    parser.add_argument("--pmtiles-bin", default="pmtiles")
    args = parser.parse_args()
    if not 0 <= args.min_zoom <= args.max_zoom <= 30:
        parser.error("los zooms deben estar entre 0 y 30 y min <= max.")
    if (
        not args.license_name.strip()
        or not args.license_url.strip()
        or not args.attribution.strip()
        or not args.source_reference.strip()
    ):
        parser.error(
            "licencia, URL de licencia, atribución y referencia de fuente son obligatorias."
        )
    if _is_remote(args.source) and not args.confirm_source_authorized:
        parser.error(
            "una fuente remota exige --confirm-source-authorized; revise antes su licencia."
        )
    if not _is_remote(args.source) and not Path(args.source).is_file():
        parser.error("la fuente local PMTiles no existe o no es un archivo.")
    if not args.style.is_file():
        parser.error("no existe el style.json local.")
    try:
        _validate_style(args.style)
    except BuildError as error:
        parser.error(str(error))
    return args


def main() -> int:
    args = _parse_args()
    version = _pmtiles_version(args.pmtiles_bin)
    output = args.output.resolve()
    if output.exists():
        raise BuildError(f"El destino ya existe: {output}. Elija una carpeta nueva.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gtfs-map-", dir=output.parent) as temporary:
        root = Path(temporary) / "package"
        root.mkdir()
        basemap = root / "basemap.pmtiles"
        _run(
            [
                args.pmtiles_bin,
                "extract",
                args.source,
                str(basemap),
                "--bbox=" + ",".join(str(value) for value in args.bbox),
                f"--minzoom={args.min_zoom}",
                f"--maxzoom={args.max_zoom}",
            ]
        )
        _run([args.pmtiles_bin, "verify", str(basemap)])
        shutil.copy2(args.style, root / "style.json")
        copied = [basemap, root / "style.json"]
        if args.assets:
            copied.extend(_copy_tree(args.assets.resolve(), root / "assets"))
        hashes = {item.relative_to(root).as_posix(): _sha256(item) for item in copied}
        manifest = {
            "version": 2,
            "package_id": output.name,
            "package_version": "1",
            "name": output.name,
            "style_profile": {
                "style_id": f"local-{args.tileset_profile}-v1",
                "style_version": "1",
                "tileset_profile": args.tileset_profile,
                "maplibre_style": "style.json",
                "required_assets": [item.relative_to(root).as_posix() for item in copied[2:]],
            },
            "basemap": "basemap.pmtiles",
            "style": "style.json",
            "license": args.license_name.strip(),
            "license_url": args.license_url.strip(),
            "attribution": args.attribution.strip(),
            "bbox": args.bbox,
            "min_zoom": args.min_zoom,
            "max_zoom": args.max_zoom,
            "source": {
                "reference": args.source_reference.strip(),
                "remote": _is_remote(args.source),
            },
            "pmtiles_version": version,
            "sha256": hashes,
        }
        (root / "package.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(root, output)
    print(json.dumps({"package": str(output), "pmtiles_version": version}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as error:
        raise SystemExit(f"Error: {error}")
