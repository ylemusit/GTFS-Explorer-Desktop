"""Convención única para nombres de artefactos de exportación."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Final

EXPORT_BASENAME_MAX_LENGTH: Final = 140
_COMPONENT_MAX_LENGTH: Final = 40
_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_REPEATED_HYPHENS = re.compile(r"-{2,}")
_RESERVED_WINDOWS_NAMES: Final = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
_EXPORT_EXTENSIONS: Final = (".geojson", ".json", ".csv", ".zip")
_CSV_MODE_SUFFIXES: Final = ("-spreadsheet-safe.csv", "-faithful.csv")


def suggest_export_filename(
    format_: str | Enum,
    *,
    route_ids: Iterable[str] = (),
    trip_ids: Iterable[str] = (),
    service_ids: Iterable[str] = (),
    spreadsheet_safe: bool = False,
) -> str:
    """Construye un basename determinista para la selección indicada.

    El identificador de ruta ocupa la posición principal porque es la unidad
    mínima exigida por los cuatro exportadores. Viajes y servicios se añaden
    solo como contexto de selección. El resultado no contiene una ruta local.
    """
    format_token, extension = _format_parts(format_, spreadsheet_safe)
    selection = _selection_token(route_ids, trip_ids, service_ids)
    return _fit_basename(f"gtfs-export-{selection}-{format_token}", extension)


def normalize_export_destination(
    format_: str | Enum, destination: Path, spreadsheet_safe: bool = False
) -> Path:
    """Asegura el basename y la extensión final del artefacto.

    La carpeta elegida por la persona usuaria se conserva. Solo se normaliza
    el nombre de archivo para evitar extensiones duplicadas, nombres Windows
    inválidos y la doble marca de modo del CSV.
    """
    format_token, extension = _format_parts(format_, spreadsheet_safe)
    if destination.name in {"", ".", ".."}:
        return destination

    stem = _without_export_suffixes(destination.name)
    stem = sanitize_export_component(stem, fallback="gtfs-export")
    if format_token.startswith("csv-"):
        stem = f"{stem}-{format_token.removeprefix('csv-')}"
    return destination.with_name(_fit_basename(stem, extension))


def sanitize_export_component(value: str, *, fallback: str = "id") -> str:
    """Convierte un identificador en un componente portable de basename."""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = _INVALID_WINDOWS_CHARS.sub("-", text)
    text = "".join("-" if character.isspace() else character for character in text)
    text = _REPEATED_HYPHENS.sub("-", text).strip(" .-")
    if not text or text.casefold() in {".", ".."}:
        text = fallback
    if text.casefold() in _RESERVED_WINDOWS_NAMES:
        text = f"id-{text}"
    return text


def _format_parts(format_: str | Enum, spreadsheet_safe: bool) -> tuple[str, str]:
    value = format_.value if isinstance(format_, Enum) else format_
    if not isinstance(value, str):
        raise ValueError("El formato de exportación no es válido.")
    key = value.casefold().replace("-", "_")
    if key == "json":
        return "json", ".json"
    if key == "geojson":
        return "geojson", ".geojson"
    if key == "csv":
        mode = "spreadsheet-safe" if spreadsheet_safe else "faithful"
        return f"csv-{mode}", ".csv"
    if key == "mini_gtfs":
        return "mini-gtfs", ".zip"
    raise ValueError(f"Formato de exportación no soportado: {value}")


def _selection_token(
    route_ids: Iterable[str], trip_ids: Iterable[str], service_ids: Iterable[str]
) -> str:
    parts: list[str] = []
    for label, values in (
        ("route", route_ids),
        ("trip", trip_ids),
        ("service", service_ids),
    ):
        identifiers = _identifier_tokens(values)
        if identifiers:
            parts.append(f"{label}-{'-'.join(identifiers)}")
    return "-".join(parts) if parts else "selection"


def _identifier_tokens(values: Iterable[str]) -> tuple[str, ...]:
    identifiers = sorted(
        {sanitize_export_component(value, fallback="id") for value in values},
        key=lambda value: (value.casefold(), value),
    )
    return tuple(_shorten_component(identifier) for identifier in identifiers)


def _shorten_component(value: str) -> str:
    if len(value) <= _COMPONENT_MAX_LENGTH:
        return value
    digest = sha256(value.encode("utf-8")).hexdigest()[:8]
    prefix = value[: _COMPONENT_MAX_LENGTH - len(digest) - 1].rstrip(" .-")
    return f"{prefix}-{digest}"


def _without_export_suffixes(name: str) -> str:
    stem = name
    while True:
        lowered = stem.casefold()
        suffixes = (*_CSV_MODE_SUFFIXES, *_EXPORT_EXTENSIONS)
        suffix = next(
            (candidate for candidate in suffixes if lowered.endswith(candidate.casefold())),
            None,
        )
        if suffix is None or len(stem) <= len(suffix):
            return stem
        stem = stem[: -len(suffix)]


def _fit_basename(stem: str, extension: str) -> str:
    safe_stem = sanitize_export_component(stem, fallback="gtfs-export")
    maximum_stem_length = EXPORT_BASENAME_MAX_LENGTH - len(extension)
    if len(safe_stem) > maximum_stem_length:
        digest = sha256(safe_stem.encode("utf-8")).hexdigest()[:8]
        prefix = safe_stem[: maximum_stem_length - len(digest) - 1].rstrip(" .-")
        safe_stem = f"{prefix}-{digest}"
    return f"{safe_stem}{extension}"
