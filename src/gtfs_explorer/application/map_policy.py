"""Contrato de modos de mapa y frontera de privacidad de las peticiones."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Final
from urllib.parse import urlsplit


class MapPolicyError(ValueError):
    """Una configuración de mapa no cumple el contrato offline-first."""


class MapMode(str, Enum):
    """Preferencia global de acceso a recursos cartográficos."""

    AUTO = "auto"
    OFFLINE = "offline"
    ONLINE = "online"


class MapAvailability(str, Enum):
    """Origen cartográfico que está activo en la vista."""

    LOCAL = "local"
    ONLINE = "online"
    UNAVAILABLE = "unavailable"


class MapCoverage(str, Enum):
    """Relación entre el overlay GTFS y los límites del paquete local."""

    LOCAL_COVERAGE = "local_coverage"
    OUTSIDE_LOCAL_COVERAGE = "outside_local_coverage"
    UNKNOWN_COVERAGE = "unknown_coverage"


@dataclass(frozen=True)
class MapPolicyDecision:
    """Resultado determinista de resolver una preferencia de mapa."""

    mode: MapMode
    availability: MapAvailability
    local_available: bool
    online_available: bool
    reason: str
    coverage: MapCoverage = MapCoverage.UNKNOWN_COVERAGE
    provider_name: str | None = None

    @property
    def source_label(self) -> str:
        return {
            MapAvailability.LOCAL: "local/offline",
            MapAvailability.ONLINE: "online",
            MapAvailability.UNAVAILABLE: "no disponible",
        }[self.availability]

    @property
    def status_text(self) -> str:
        """Texto breve y apto para mostrar junto al mapa."""
        return f"Mapa: {self.source_label} · {self.reason}"


def normalize_map_mode(value: MapMode | str) -> MapMode:
    """Acepta el enum público y sus valores serializables en minúsculas."""
    if isinstance(value, MapMode):
        return value
    try:
        return MapMode(value.casefold())
    except (AttributeError, ValueError) as error:
        raise MapPolicyError("El modo de mapa debe ser AUTO, OFFLINE u ONLINE.") from error


def resolve_map_policy(
    mode: MapMode | str,
    *,
    local_available: bool,
    online_available: bool = False,
    coverage: MapCoverage | str = MapCoverage.UNKNOWN_COVERAGE,
    provider_name: str | None = None,
) -> MapPolicyDecision:
    """Resuelve la prioridad local/remota sin comprobar Internet ni hacer I/O.

    ``online_available`` significa que existe un proveedor remoto explícitamente
    configurado; no se interpreta como una autorización para probar la red.
    """
    normalized = normalize_map_mode(mode)
    normalized_coverage = normalize_map_coverage(coverage)
    effective_local = local_available
    if normalized_coverage is MapCoverage.LOCAL_COVERAGE:
        effective_local = True
    elif normalized_coverage is MapCoverage.OUTSIDE_LOCAL_COVERAGE:
        effective_local = False
    if normalized is MapMode.AUTO:
        if effective_local:
            return _decision(
                normalized,
                MapAvailability.LOCAL,
                effective_local,
                online_available,
                "Se utiliza el paquete PMTiles local validado.",
                normalized_coverage,
                provider_name,
            )
        if online_available:
            return _decision(
                normalized,
                MapAvailability.ONLINE,
                effective_local,
                online_available,
                "Se utiliza únicamente el recurso cartográfico remoto permitido.",
                normalized_coverage,
                provider_name,
            )
        reason = (
            "Sin cobertura de mapa offline."
            if normalized_coverage is MapCoverage.OUTSIDE_LOCAL_COVERAGE
            else "No hay paquete local ni proveedor online configurado."
        )
        return _decision(
            normalized,
            MapAvailability.UNAVAILABLE,
            effective_local,
            online_available,
            reason,
            normalized_coverage,
            provider_name,
        )

    if normalized is MapMode.OFFLINE:
        if effective_local:
            return _decision(
                normalized,
                MapAvailability.LOCAL,
                effective_local,
                online_available,
                "Se utiliza el paquete PMTiles local validado.",
                normalized_coverage,
                provider_name,
            )
        reason = (
            "Sin cobertura de mapa offline; la red está bloqueada."
            if normalized_coverage is MapCoverage.OUTSIDE_LOCAL_COVERAGE
            else "No hay paquete PMTiles local; la red está bloqueada."
        )
        return _decision(
            normalized,
            MapAvailability.UNAVAILABLE,
            effective_local,
            online_available,
            reason,
            normalized_coverage,
            provider_name,
        )

    if online_available:
        return _decision(
            normalized,
            MapAvailability.ONLINE,
            effective_local,
            online_available,
            "Se utiliza únicamente el recurso cartográfico remoto permitido.",
            normalized_coverage,
            provider_name,
        )
    return _decision(
        normalized,
        MapAvailability.UNAVAILABLE,
        effective_local,
        online_available,
        "No hay proveedor online configurado.",
        normalized_coverage,
        provider_name,
    )


def _decision(
    mode: MapMode,
    availability: MapAvailability,
    local_available: bool,
    online_available: bool,
    reason: str,
    coverage: MapCoverage,
    provider_name: str | None,
) -> MapPolicyDecision:
    return MapPolicyDecision(
        mode,
        availability,
        local_available,
        online_available,
        reason,
        coverage,
        provider_name,
    )


def normalize_map_coverage(value: MapCoverage | str) -> MapCoverage:
    """Normaliza el estado de cobertura sin inspeccionar teselas individuales."""
    if isinstance(value, MapCoverage):
        return value
    try:
        return MapCoverage(value.casefold())
    except (AttributeError, ValueError) as error:
        raise MapPolicyError("La cobertura de mapa no es válida.") from error


_LOCAL_SCHEMES: Final = frozenset({"about", "blob", "data", "file", "qrc"})
_HTTP_SCHEMES: Final = frozenset({"http", "https"})
_TILE_PLACEHOLDER = re.compile(r"{([^{}]+)}")
_FORBIDDEN_TEMPLATE_PARTS: Final = (
    "access_token",
    "api_key",
    "apikey",
    "bbox",
    "route_id",
    "secret",
    "stop_id",
    "token",
    "trip_id",
    "workspace",
)


@dataclass
class MapRequestPolicy:
    """Allowlist de recursos WebEngine, sin guardar las URLs bloqueadas."""

    mode: MapMode = MapMode.AUTO
    local_origin: str | None = None
    online_origins: tuple[str, ...] = ()
    active_availability: MapAvailability | None = None

    def __post_init__(self) -> None:
        self.mode = normalize_map_mode(self.mode)
        if self.local_origin is not None:
            self.local_origin = _normalize_origin(self.local_origin)
        self.online_origins = tuple(_normalize_origin(origin) for origin in self.online_origins)

    def set_mode(self, mode: MapMode | str) -> None:
        self.mode = normalize_map_mode(mode)

    def set_local_origin(self, origin: str | None) -> None:
        self.local_origin = None if origin is None else _normalize_origin(origin)

    def set_active_availability(self, availability: MapAvailability | None) -> None:
        """Limita la red al basemap realmente activo, sin guardar URLs."""
        self.active_availability = availability

    def allows(self, url: str) -> bool:
        """Permite solo recursos internos o un origen remoto explícito."""
        if not isinstance(url, str):
            return False
        try:
            parsed = urlsplit(url)
        except ValueError:
            return False
        scheme = parsed.scheme.casefold()
        if scheme in _LOCAL_SCHEMES:
            return True
        if scheme not in _HTTP_SCHEMES or not parsed.netloc:
            return False
        if parsed.query or parsed.fragment:
            return False
        try:
            origin = _request_origin(url)
        except MapPolicyError:
            return False
        if origin == self.local_origin:
            return True
        if self.mode is MapMode.OFFLINE:
            return False
        if (
            self.active_availability is not None
            and self.active_availability is not MapAvailability.ONLINE
        ):
            return False
        return origin in self.online_origins


def _normalize_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        # Acceder a port fuerza la validación de puertos inválidos.
        _ = parsed.port
    except (AttributeError, TypeError, ValueError) as error:
        raise MapPolicyError("El origen de mapa no es una URL válida.") from error
    if (
        parsed.scheme.casefold() not in _HTTP_SCHEMES
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise MapPolicyError("El origen de mapa debe ser http(s) sin ruta, credenciales ni query.")
    return _request_origin(value)


def _request_origin(value: str) -> str:
    """Devuelve el origen de una URL HTTP sin imponer que la ruta esté vacía."""
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except (AttributeError, TypeError, ValueError) as error:
        raise MapPolicyError("La URL de la petición no es válida.") from error
    if (
        parsed.scheme.casefold() not in _HTTP_SCHEMES
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise MapPolicyError("La petición debe usar un origen HTTP sin credenciales.")
    return f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}"


def build_external_tile_url(template: str, *, z: int, x: int, y: int) -> str:
    """Construye una URL de tesela usando únicamente ``z``, ``x`` e ``y``.

    Query strings, credenciales, tokens, claves y contexto GTFS se rechazan
    antes de generar la URL.
    """
    if not isinstance(template, str) or not template.strip():
        raise MapPolicyError("La plantilla de teselas no puede estar vacía.")
    if any(type(value) is not int or value < 0 for value in (z, x, y)):
        raise MapPolicyError("Las coordenadas de tesela deben ser enteros no negativos.")
    try:
        parsed = urlsplit(template)
        _ = parsed.port
    except (AttributeError, TypeError, ValueError) as error:
        raise MapPolicyError("La plantilla de teselas no es una URL válida.") from error
    if (
        parsed.scheme.casefold() not in _HTTP_SCHEMES
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise MapPolicyError("Las teselas externas no admiten credenciales, query ni fragmentos.")
    lowered = template.casefold()
    if any(part in lowered for part in _FORBIDDEN_TEMPLATE_PARTS):
        raise MapPolicyError(
            "La plantilla de teselas contiene contexto o credenciales no permitidos."
        )
    placeholders = _TILE_PLACEHOLDER.findall(parsed.path)
    if len(placeholders) != 3 or set(placeholders) != {"z", "x", "y"}:
        raise MapPolicyError("La URL de teselas solo puede parametrizar z, x e y.")
    try:
        result = template.format(z=z, x=x, y=y)
    except (KeyError, ValueError) as error:
        raise MapPolicyError(
            "La plantilla de teselas no se puede parametrizar de forma segura."
        ) from error
    return result


@dataclass(frozen=True)
class OnlineMapProvider:
    """Definición central del único proveedor online interactivo habilitado."""

    name: str
    tile_url_template: str
    attribution: str
    tile_size: int = 256
    min_zoom: int = 0
    max_zoom: int = 19

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise MapPolicyError("El proveedor online debe tener un nombre.")
        if not isinstance(self.attribution, str) or not self.attribution.strip():
            raise MapPolicyError("El proveedor online debe declarar atribución.")
        if type(self.tile_size) is not int or self.tile_size <= 0:
            raise MapPolicyError("El tamaño de tesela del proveedor no es válido.")
        if (
            type(self.min_zoom) is not int
            or type(self.max_zoom) is not int
            or not 0 <= self.min_zoom <= self.max_zoom <= 30
        ):
            raise MapPolicyError("El rango de zoom del proveedor no es válido.")
        try:
            parsed = urlsplit(self.tile_url_template)
        except (AttributeError, TypeError, ValueError) as error:
            raise MapPolicyError("La plantilla del proveedor no es válida.") from error
        if parsed.scheme.casefold() != "https":
            raise MapPolicyError("El proveedor online debe usar HTTPS.")
        build_external_tile_url(self.tile_url_template, z=0, x=0, y=0)

    @property
    def origin(self) -> str:
        return _request_origin(self.tile_url_template)

    def tile_url(self, *, z: int, x: int, y: int) -> str:
        """Devuelve una tesela sin añadir ningún dato del feed o del workspace."""
        return build_external_tile_url(self.tile_url_template, z=z, x=x, y=y)


DEFAULT_ONLINE_MAP_PROVIDER = OnlineMapProvider(
    name="OpenStreetMap Standard",
    tile_url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution="© OpenStreetMap contributors",
)


__all__ = (
    "MapAvailability",
    "MapCoverage",
    "MapMode",
    "OnlineMapProvider",
    "DEFAULT_ONLINE_MAP_PROVIDER",
    "MapPolicyDecision",
    "MapPolicyError",
    "MapRequestPolicy",
    "build_external_tile_url",
    "normalize_map_mode",
    "normalize_map_coverage",
    "resolve_map_policy",
)
