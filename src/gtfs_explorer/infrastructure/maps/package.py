"""Contrato estricto para paquetes PMTiles offline.

El paquete no es una fuente de confianza: todos sus activos se verifican antes
de exponerlos al WebEngine.  No se resuelven URL remotas ni rutas fuera de la
carpeta seleccionada.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


class MapPackageError(ValueError):
    """El paquete de mapa no es seguro o no cumple el contrato v1."""


@dataclass(frozen=True)
class MapPackage:
    root: Path
    basemap: Path
    style: Path
    attribution: str
    license_name: str
    license_url: str
    source_reference: str
    pmtiles_version: str
    bbox: tuple[float, float, float, float]
    min_zoom: int
    max_zoom: int
    files: tuple[PurePosixPath, ...]


def load_map_package(root: Path) -> MapPackage:
    """Valida y carga un paquete sin hacer peticiones de red."""
    root = root.resolve()
    manifest_path = root / "package.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MapPackageError("No se puede leer package.json del mapa.") from error
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise MapPackageError("El paquete de mapa no usa el contrato v1.")
    required = (
        "basemap",
        "style",
        "license",
        "license_url",
        "attribution",
        "bbox",
        "min_zoom",
        "max_zoom",
        "source",
        "pmtiles_version",
        "sha256",
    )
    if any(name not in payload for name in required):
        raise MapPackageError("Faltan campos obligatorios en package.json.")
    basemap = _safe_file(root, payload["basemap"])
    style = _safe_file(root, payload["style"])
    if not isinstance(payload["license"], str) or not payload["license"].strip():
        raise MapPackageError("El paquete no declara una licencia.")
    if not isinstance(payload["license_url"], str) or not payload["license_url"].strip():
        raise MapPackageError("El paquete no declara la referencia de licencia.")
    if not isinstance(payload["attribution"], str) or not payload["attribution"].strip():
        raise MapPackageError("El paquete no declara una atribución visible.")
    bbox = _bbox(payload["bbox"])
    min_zoom, max_zoom = _zooms(payload["min_zoom"], payload["max_zoom"])
    source_reference = _source_reference(payload["source"])
    if not isinstance(payload["pmtiles_version"], str) or not payload["pmtiles_version"].strip():
        raise MapPackageError("El paquete no declara la versión de pmtiles.")
    hashes = payload["sha256"]
    if not isinstance(hashes, dict) or not hashes:
        raise MapPackageError("El paquete no declara hashes SHA-256.")
    files = tuple(_verify_hash(root, item, digest) for item, digest in hashes.items())
    if basemap.relative_to(root).as_posix() not in {item.as_posix() for item in files}:
        raise MapPackageError("El PMTiles no está protegido por un hash.")
    if style.relative_to(root).as_posix() not in {item.as_posix() for item in files}:
        raise MapPackageError("El estilo no está protegido por un hash.")
    _validate_pmtiles(basemap)
    _validate_style(style)
    return MapPackage(
        root,
        basemap,
        style,
        payload["attribution"].strip(),
        payload["license"].strip(),
        payload["license_url"].strip(),
        source_reference,
        payload["pmtiles_version"].strip(),
        bbox,
        min_zoom,
        max_zoom,
        files,
    )


def _safe_file(root: Path, value: Any) -> Path:
    if not isinstance(value, str):
        raise MapPackageError("La ruta de un activo no es válida.")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise MapPackageError("El paquete contiene una ruta de activo insegura.")
    path = (root / Path(*relative.parts)).resolve()
    if root not in path.parents or not path.is_file():
        raise MapPackageError("Falta un activo declarado por el paquete.")
    return path


def _verify_hash(root: Path, item: Any, digest: Any) -> PurePosixPath:
    path = _safe_file(root, item)
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest.casefold())
    ):
        raise MapPackageError("Un hash SHA-256 no es válido.")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest.casefold():
        raise MapPackageError(f"El hash no coincide para '{item}'.")
    return PurePosixPath(path.relative_to(root).as_posix())


def _bbox(value: Any) -> tuple[float, float, float, float]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(isinstance(v, (int, float)) for v in value)
    ):
        raise MapPackageError("bbox debe contener cuatro coordenadas numéricas.")
    west, south, east, north = (float(v) for v in value)
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise MapPackageError("bbox está fuera de los límites WGS84.")
    return west, south, east, north


def _zooms(minimum: Any, maximum: Any) -> tuple[int, int]:
    if type(minimum) is not int or type(maximum) is not int or not 0 <= minimum <= maximum <= 30:
        raise MapPackageError("El rango de zoom no es válido.")
    return minimum, maximum


def _source_reference(value: Any) -> str:
    if not isinstance(value, dict):
        raise MapPackageError("El paquete no declara la fuente del mapa.")
    reference = value.get("reference")
    if (
        not isinstance(reference, str)
        or not reference.strip()
        or type(value.get("remote")) is not bool
    ):
        raise MapPackageError("La referencia de la fuente no es válida.")
    return reference.strip()


def _validate_pmtiles(path: Path) -> None:
    header = path.read_bytes()[:8]
    if len(header) != 8 or header[:7] != b"PMTiles" or header[7] != 3:
        raise MapPackageError("basemap.pmtiles no es un PMTiles v3 válido.")


def _validate_style(path: Path) -> None:
    try:
        style = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MapPackageError("style.json no es JSON válido.") from error
    if not isinstance(style, dict) or style.get("version") != 8:
        raise MapPackageError("style.json no es un estilo MapLibre v8.")
    if _contains_remote_url(style):
        raise MapPackageError("style.json contiene una URL remota no permitida.")


def _contains_remote_url(value: Any) -> bool:
    if isinstance(value, str):
        return value.casefold().startswith(("http://", "https://", "//"))
    if isinstance(value, dict):
        return any(_contains_remote_url(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_remote_url(item) for item in value)
    return False
