"""Identidad canónica del producto reutilizable en aplicación y empaquetado.

La versión solo se declara una vez en este módulo. El resto de la aplicación,
las herramientas y los builders consumen ``IDENTITY.version`` o el alias
``PRODUCT_VERSION`` para no mantener copias divergentes.
"""

from __future__ import annotations

import os
import platform
import re
from collections.abc import Mapping
from dataclasses import dataclass

PRODUCT_VERSION = "0.1.0"
GTFS_SPEC_REVISION = "2026-04-27"

_BUILD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class ProductIdentity:
    """Metadatos estables que no dependen de la capa de presentación."""

    name: str
    edition: int
    author: str
    copyright_year: int
    rights_notice: str
    executable_name: str = "GTFS Explorer.exe"
    install_directory_name: str = "GTFS Explorer"
    start_menu_directory_name: str = "GTFS Explorer"
    shortcut_name: str = "GTFS Explorer Desktop.lnk"
    # Debe ser corto: Windows Explorer concatena esta raíz con el nombre
    # completo del ZIP al extraer el Portable.
    portable_directory_name: str = "GTFS-Explorer"
    version: str = PRODUCT_VERSION
    gtfs_spec_revision: str = GTFS_SPEC_REVISION

    @property
    def windows_file_version(self) -> str:
        """Versión numérica de cuatro componentes para recursos PE/Windows."""
        return windows_file_version(self.version)

    @property
    def windows_product_version(self) -> str:
        """Versión numérica del producto aceptada por Nuitka y NSIS."""
        return windows_product_version(self.version)

    @property
    def file_description(self) -> str:
        return "Explorador local de datos GTFS Schedule"

    @property
    def copyright_text(self) -> str:
        return f"Copyright {self.copyright_year} {self.author}. {self.rights_notice}"


IDENTITY = ProductIdentity(
    name="GTFS Explorer Desktop",
    edition=2026,
    author="Yeison Arbey Carrillo Lemus",
    copyright_year=2026,
    rights_notice="Todos los derechos reservados.",
)


def _numeric_version_parts(version: str) -> tuple[str, ...]:
    release = version.split("-", maxsplit=1)[0]
    parts = tuple(release.split("."))
    if not 1 <= len(parts) <= 4 or any(not part.isdigit() for part in parts):
        raise ValueError(f"La versión no es compatible con metadata Windows: {version!r}")
    if any(int(part) >= 65536 for part in parts):
        raise ValueError(f"La versión excede el rango de metadata Windows: {version!r}")
    return parts


def windows_product_version(version: str) -> str:
    """Convierte una versión de producto a la representación PE numérica."""
    return ".".join(_numeric_version_parts(version))


def windows_file_version(version: str) -> str:
    """Devuelve siempre cuatro componentes para ``FileVersion`` de Windows."""
    parts = _numeric_version_parts(version)
    return ".".join((*parts, *("0",) * (4 - len(parts))))


def runtime_build_id(environ: Mapping[str, str] | None = None) -> str:
    """Obtiene un identificador de build seguro para UI y diagnósticos.

    El valor lo puede proporcionar el pipeline mediante
    ``GTFS_EXPLORER_BUILD_ID``. Si falta o no tiene formato de identificador,
    se usa ``local`` y nunca se muestra el contenido arbitrario de la variable.
    """
    source = os.environ if environ is None else environ
    candidate = source.get("GTFS_EXPLORER_BUILD_ID", "").strip()
    return candidate if _BUILD_ID_PATTERN.fullmatch(candidate) else "local"


def runtime_architecture() -> str:
    """Describe el sistema y la arquitectura sin exponer rutas ni datos locales."""
    machine = platform.machine().casefold()
    architecture = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "ARM64",
        "aarch64": "ARM64",
        "x86": "x86",
        "i386": "x86",
        "i686": "x86",
    }.get(machine, platform.machine() or "desconocida")
    return f"{platform.system() or 'Sistema'} {architecture}"
