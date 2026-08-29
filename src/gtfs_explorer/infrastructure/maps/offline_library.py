"""Biblioteca global de datasets PMTiles y paquetes de basemap offline.

Un PMTiles correcto no implica que GTFS Explorer sepa dibujarlo. El índice
guarda ambas cosas por separado y solo publica paquetes completos.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import BinaryIO, Callable, cast
from urllib.request import urlopen

from gtfs_explorer.infrastructure.filesystem.paths import default_local_app_data_directory
from gtfs_explorer.infrastructure.maps.package import MapPackageError, load_map_package


class OfflineMapError(ValueError):
    """El dataset o paquete no cumple el contrato local."""


class TileType(str, Enum):
    VECTOR = "vector"
    RASTER = "raster"
    UNKNOWN = "unknown"


class RenderStatus(str, Enum):
    RENDERABLE_BASEMAP = "renderable_basemap"
    UNSUPPORTED_STYLE = "unsupported_style"


class CoverageStatus(str, Enum):
    COVERED = "covered"
    PARTIALLY_COVERED = "partially_covered"
    NOT_COVERED = "not_covered"
    UNKNOWN = "unknown"


class DownloadCapability(str, Enum):
    PREBUILT_PACKAGE = "prebuilt_package"
    BBOX_EXTRACT = "bbox_extract"


@dataclass(frozen=True)
class ProjectMapCoverage:
    bounds: tuple[float, float, float, float] | None
    source: str | None = None


@dataclass(frozen=True)
class OfflineMapPackage:
    package_id: str
    name: str
    file_name: str
    bounds: tuple[float, float, float, float] | None
    minzoom: int | None
    maxzoom: int | None
    size: int
    source: str | None
    version: str | None
    attribution: str | None
    license: str | None
    checksum: str | None
    checksum_algorithm: str | None
    installed_at: str
    tile_type: TileType = TileType.UNKNOWN
    render_status: RenderStatus = RenderStatus.UNSUPPORTED_STYLE
    style_id: str | None = None

    @property
    def is_renderable(self) -> bool:
        return self.render_status is RenderStatus.RENDERABLE_BASEMAP


@dataclass(frozen=True)
class OfflineMapCatalogEntry:
    package_id: str
    name: str
    bounds: tuple[float, float, float, float] | None
    minzoom: int | None
    maxzoom: int | None
    size: int | None
    url: str | None
    checksum: str | None
    checksum_algorithm: str | None
    attribution: str | None
    license: str | None
    source: str | None
    version: str | None
    capability: DownloadCapability = DownloadCapability.PREBUILT_PACKAGE
    style_bundle: str | None = None
    offline_ready: bool = False


def default_map_library_path() -> Path:
    return default_local_app_data_directory() / "GTFS Explorer" / "maps"


class OfflineMapLibrary:
    """Índice local v2: paths relativos y renderizabilidad explícita."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_map_library_path()
        self.index_path = self.root / "index.json"
        self.packages_path = self.root / "packages"

    def installed_maps(self) -> tuple[OfflineMapPackage, ...]:
        return tuple(
            sorted(
                (_package_from_dict(x) for x in self._read_index()),
                key=lambda x: (x.name.casefold(), x.package_id, x.version or ""),
            )
        )

    def package_root(self, item: OfflineMapPackage) -> Path:
        path = (self.packages_path / item.file_name).resolve()
        if self.packages_path.resolve() not in path.parents:
            raise OfflineMapError("El índice contiene una ruta de paquete insegura.")
        return path

    def import_file(
        self,
        source: Path,
        *,
        package_id: str | None = None,
        name: str | None = None,
        source_name: str | None = None,
        version: str | None = None,
        checksum: str | None = None,
        checksum_algorithm: str | None = None,
        attribution: str | None = None,
        license: str | None = None,
    ) -> OfflineMapPackage:
        """Registra un dataset válido; solo raster genera estilo local mínimo."""
        if not source.is_file():
            raise OfflineMapError("No existe el archivo PMTiles seleccionado.")
        header = read_pmtiles_metadata(source)
        metadata = cast(dict[str, object], header["metadata"])
        identifier = _identifier(package_id or source.stem)
        expected = _checksum(checksum, checksum_algorithm)
        if expected and _digest(source, expected[0]) != expected[1]:
            raise OfflineMapError("El checksum del paquete PMTiles no coincide.")
        tile_type = cast(TileType, header["tile_type"])
        raster = tile_type is TileType.RASTER
        item = OfflineMapPackage(
            identifier,
            _text(name) or source.stem,
            f"{identifier}/{_text(version) or 'imported'}",
            cast(tuple[float, float, float, float] | None, header["bounds"]),
            _int_or_none(header["minzoom"]),
            _int_or_none(header["maxzoom"]),
            source.stat().st_size,
            _text(source_name) or _text(metadata.get("source")),
            _text(version) or _text(metadata.get("version")),
            _text(attribution) or _text(metadata.get("attribution")),
            _text(license) or _text(metadata.get("license")),
            expected[1] if expected else _digest(source, "sha256"),
            expected[0] if expected else "sha256",
            datetime.now(UTC).isoformat(),
            tile_type,
            RenderStatus.RENDERABLE_BASEMAP if raster else RenderStatus.UNSUPPORTED_STYLE,
            "builtin-raster-v1" if raster else None,
        )
        self._install(lambda staging: _copy_raw_dataset(source, staging, item, raster), item)
        return item

    def import_package(self, root: Path) -> OfflineMapPackage:
        """Instala un bundle vectorial/raster ya validado, como unidad atómica."""
        try:
            package = load_map_package(root)
        except MapPackageError as error:
            raise OfflineMapError(str(error)) from error
        header = read_pmtiles_metadata(package.basemap)
        item = OfflineMapPackage(
            package.package_id,
            package.name,
            f"{package.package_id}/{package.package_version}",
            package.bbox,
            package.min_zoom,
            package.max_zoom,
            package.basemap.stat().st_size,
            package.source_reference,
            package.package_version,
            package.attribution,
            package.license_name,
            _digest(package.basemap, "sha256"),
            "sha256",
            datetime.now(UTC).isoformat(),
            cast(TileType, header["tile_type"]),
            RenderStatus.RENDERABLE_BASEMAP,
            package.style_id,
        )
        self._install(lambda staging: shutil.copytree(root, staging, dirs_exist_ok=True), item)
        return item

    def download(
        self,
        entry: OfflineMapCatalogEntry,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        on_progress: Callable[[int, int | None], None] = lambda _done, _total: None,
        opener: Callable[[str], BinaryIO] | None = None,
    ) -> OfflineMapPackage:
        if entry.capability is not DownloadCapability.PREBUILT_PACKAGE or not entry.url:
            raise OfflineMapError("BACKLOG: descarga exacta PMTiles por bbox.")
        if entry.offline_ready and not entry.style_bundle:
            raise OfflineMapError("El catálogo promete offline sin declarar el bundle de estilo.")
        self.root.mkdir(parents=True, exist_ok=True)
        part = self.root / f".{_identifier(entry.package_id)}.part"
        try:
            response = opener(entry.url) if opener else urlopen(entry.url, timeout=30)  # noqa: S310
            with response, part.open("wb") as output:
                total = _content_length(response) or entry.size
                done = 0
                while chunk := response.read(1024 * 1024):
                    if cancelled():
                        raise OfflineMapError("Descarga cancelada.")
                    output.write(chunk)
                    done += len(chunk)
                    on_progress(done, total)
                output.flush()
                os.fsync(output.fileno())
            return self.import_file(
                part,
                package_id=entry.package_id,
                name=entry.name,
                source_name=entry.source,
                version=entry.version,
                checksum=entry.checksum,
                checksum_algorithm=entry.checksum_algorithm,
                attribution=entry.attribution,
                license=entry.license,
            )
        finally:
            part.unlink(missing_ok=True)

    def remove(self, package_id: str, version: str | None = None) -> None:
        entries = self._read_index()
        matches = [
            x
            for x in entries
            if x.get("package_id") == package_id
            and (version is None or x.get("version") == version)
        ]
        if not matches:
            raise OfflineMapError("El mapa indicado no está instalado.")
        for entry in matches:
            shutil.rmtree(self.package_root(_package_from_dict(entry)))
        self._write_index([x for x in entries if x not in matches])

    def _install(self, populate: Callable[[Path], None], item: OfflineMapPackage) -> None:
        entries = self._read_index()
        if any(
            x.get("package_id") == item.package_id and x.get("version") == item.version
            for x in entries
        ):
            raise OfflineMapError("Ya existe un paquete con el mismo id y versión.")
        self.packages_path.mkdir(parents=True, exist_ok=True)
        destination = self.package_root(item)
        if destination.exists():
            raise OfflineMapError("Ya existe un archivo de mapa con ese nombre.")
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=self.packages_path))
        try:
            populate(staging)
            if item.is_renderable:
                load_map_package(staging)
            else:
                read_pmtiles_metadata(staging / "map.pmtiles")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, destination)
            self._write_index([*entries, asdict(item)])
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(destination, ignore_errors=True)
            raise

    def _read_index(self) -> list[dict[str, object]]:
        if not self.index_path.exists():
            return []
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OfflineMapError("El índice local de mapas no se puede leer.") from error
        if (
            not isinstance(value, dict)
            or value.get("version") != 2
            or not isinstance(value.get("maps"), list)
        ):
            raise OfflineMapError("El índice local de mapas no es compatible.")
        return [cast(dict[str, object], x) for x in value["maps"] if isinstance(x, dict)]

    def _write_index(self, entries: list[dict[str, object]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump({"version": 2, "maps": entries}, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.index_path)


def read_pmtiles_metadata(path: Path) -> dict[str, object]:
    size = path.stat().st_size
    if size < 8:
        raise OfflineMapError("El archivo PMTiles está truncado.")
    with path.open("rb") as file:
        header = file.read(127)
        if len(header) < 8 or header[:7] != b"PMTiles" or header[7] != 3:
            raise OfflineMapError("El archivo no contiene un header PMTiles v3 compatible.")
        if len(header) < 127:
            return {
                "metadata": {},
                "bounds": None,
                "minzoom": None,
                "maxzoom": None,
                "tile_type": TileType.UNKNOWN,
            }
        for offset_index, length_index in ((8, 16), (24, 32), (40, 48), (56, 64)):
            if (
                int.from_bytes(header[offset_index : offset_index + 8], "little")
                + int.from_bytes(header[length_index : length_index + 8], "little")
                > size
            ):
                raise OfflineMapError("El archivo PMTiles parece truncado.")
        offset, length = (
            int.from_bytes(header[24:32], "little"),
            int.from_bytes(header[32:40], "little"),
        )
        metadata: dict[str, object] = {}
        if length:
            file.seek(offset)
            try:
                value = json.loads(file.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise OfflineMapError("La metadata PMTiles no es JSON válido.") from error
            if not isinstance(value, dict):
                raise OfflineMapError("La metadata PMTiles no es un objeto.")
            metadata = value
    return {
        "metadata": metadata,
        "bounds": _bounds(header[102:118]),
        "minzoom": int(header[100]),
        "maxzoom": int(header[101]),
        "tile_type": TileType.VECTOR
        if header[99] == 1
        else TileType.RASTER
        if header[99] in {2, 3, 4}
        else TileType.UNKNOWN,
    }


def classify_coverage(coverage: ProjectMapCoverage, package: OfflineMapPackage) -> CoverageStatus:
    if coverage.bounds is None or package.bounds is None:
        return CoverageStatus.UNKNOWN
    west, south, east, north = coverage.bounds
    pw, ps, pe, pn = package.bounds
    if pw <= west and south >= ps and east <= pe and north <= pn:
        return CoverageStatus.COVERED
    return (
        CoverageStatus.PARTIALLY_COVERED
        if max(west, pw) < min(east, pe) and max(south, ps) < min(north, pn)
        else CoverageStatus.NOT_COVERED
    )


def resolve_best_map(
    coverage: ProjectMapCoverage, packages: tuple[OfflineMapPackage, ...]
) -> OfflineMapPackage | None:
    candidates = [
        x
        for x in packages
        if x.is_renderable and classify_coverage(coverage, x) is CoverageStatus.COVERED
    ]
    return (
        min(
            candidates,
            key=lambda x: (
                -(x.maxzoom or 0),
                (
                    (x.bounds[2] - x.bounds[0]) * (x.bounds[3] - x.bounds[1])
                    if x.bounds
                    else float("inf")
                ),
                x.size,
                x.package_id,
            ),
        )
        if candidates
        else None
    )


def _copy_raw_dataset(
    source: Path, root: Path, item: OfflineMapPackage, raster_style: bool
) -> None:
    shutil.copy2(source, root / "map.pmtiles")
    if not raster_style:
        return
    style = {
        "version": 8,
        "sources": {"basemap": {"type": "raster", "url": "pmtiles://map.pmtiles", "tileSize": 256}},
        "layers": [{"id": "basemap", "type": "raster", "source": "basemap"}],
    }
    (root / "style.json").write_text(json.dumps(style), encoding="utf-8")
    hashes = {name: _digest(root / name, "sha256") for name in ("map.pmtiles", "style.json")}
    manifest = {
        "version": 2,
        "package_id": item.package_id,
        "package_version": item.version or "imported",
        "name": item.name,
        "style_profile": {
            "style_id": "builtin-raster-v1",
            "style_version": "1",
            "tileset_profile": "raster",
            "maplibre_style": "style.json",
            "required_assets": [],
        },
        "basemap": "map.pmtiles",
        "style": "style.json",
        "license": item.license or "unspecified",
        "license_url": "local-import",
        "attribution": item.attribution or "No declarada por el archivo importado",
        "bbox": list(item.bounds or (-180, -90, 180, 90)),
        "min_zoom": item.minzoom or 0,
        "max_zoom": item.maxzoom or 30,
        "source": {"reference": item.source or "Importación local", "remote": False},
        "pmtiles_version": "PMTiles v3",
        "sha256": hashes,
    }
    (root / "package.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _bounds(raw: bytes) -> tuple[float, float, float, float] | None:
    values = tuple(
        int.from_bytes(raw[i : i + 4], "little", signed=True) / 10_000_000 for i in range(0, 16, 4)
    )
    return (
        cast(tuple[float, float, float, float], values)
        if -180 <= values[0] < values[2] <= 180 and -90 <= values[1] < values[3] <= 90
        else None
    )


def _identifier(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not result:
        raise OfflineMapError("El identificador del mapa no es válido.")
    return result[:80]


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _checksum(value: str | None, algorithm: str | None) -> tuple[str, str] | None:
    if value is None and algorithm is None:
        return None
    if not value or not algorithm or algorithm.casefold() not in hashlib.algorithms_available:
        raise OfflineMapError("El checksum declarado no es válido.")
    return algorithm.casefold(), value.casefold()


def _digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_length(response: BinaryIO) -> int | None:
    try:
        return int(response.headers.get("Content-Length"))  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        return None


def _package_from_dict(value: dict[str, object]) -> OfflineMapPackage:
    bounds = value.get("bounds")
    parsed = (
        cast(tuple[float, float, float, float], tuple(float(x) for x in bounds))
        if isinstance(bounds, (list, tuple)) and len(bounds) == 4
        else None
    )
    try:
        tile_type = TileType(str(value.get("tile_type", "unknown")))
        render_status = RenderStatus(str(value.get("render_status", "unsupported_style")))
    except ValueError as error:
        raise OfflineMapError("El índice local contiene un tipo de mapa inválido.") from error
    size = value.get("size")
    if type(size) is not int:
        raise OfflineMapError("El índice local contiene un tamaño de mapa inválido.")
    return OfflineMapPackage(
        str(value["package_id"]),
        str(value["name"]),
        str(value["file_name"]),
        parsed,
        _int_or_none(value.get("minzoom")),
        _int_or_none(value.get("maxzoom")),
        size,
        _text(value.get("source")),
        _text(value.get("version")),
        _text(value.get("attribution")),
        _text(value.get("license")),
        _text(value.get("checksum")),
        _text(value.get("checksum_algorithm")),
        str(value["installed_at"]),
        tile_type,
        render_status,
        _text(value.get("style_id")),
    )


def _int_or_none(value: object) -> int | None:
    return value if type(value) is int else None
