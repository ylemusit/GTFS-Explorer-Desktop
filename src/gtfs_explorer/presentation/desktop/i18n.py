"""Catálogos locales de interfaz con fallback seguro y cambio dinámico."""

from __future__ import annotations

import json
from importlib.resources import files

SUPPORTED_LOCALES: tuple[str, ...] = ("es-ES", "en", "de-DE", "ja-JP", "zh-CN")
_LOCALE_LABELS = {
    "es-ES": "Español",
    "en": "English",
    "de-DE": "Deutsch",
    "ja-JP": "日本語",
    "zh-CN": "简体中文",
}


def _catalog(locale: str) -> dict[str, str]:
    filename = "es.json" if locale == "es-ES" else f"{locale}.json"
    payload = json.loads(
        files("gtfs_explorer.resources.i18n").joinpath(filename).read_text("utf-8")
    )
    messages = payload.get("messages")
    if not isinstance(messages, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in messages.items()
    ):
        raise ValueError(f"El catálogo de interfaz {locale} no es válido.")
    return messages


def _normalise_locale(locale: str | None) -> str:
    if not isinstance(locale, str):
        return "es-ES"
    candidate = locale.strip().replace("_", "-")
    aliases = {"es": "es-ES", "de": "de-DE", "ja": "ja-JP", "zh": "zh-CN"}
    candidate = aliases.get(candidate.casefold(), candidate)
    if candidate in SUPPORTED_LOCALES:
        return candidate
    return "en"


_SPANISH_MESSAGES = _catalog("es-ES")
try:
    _ENGLISH_MESSAGES = _catalog("en")
except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
    _ENGLISH_MESSAGES = {}

MESSAGES = dict(_SPANISH_MESSAGES)
_ACTIVE_LOCALE = "es-ES"


def current_locale() -> str:
    """Devuelve el locale activo de la interfaz."""
    return _ACTIVE_LOCALE


def supported_locales() -> tuple[str, ...]:
    """Locales disponibles en la distribución, en el orden del selector."""
    return SUPPORTED_LOCALES


def locale_label(locale: str) -> str:
    """Nombre legible de un locale para el selector de ajustes."""
    return _LOCALE_LABELS.get(_normalise_locale(locale), _LOCALE_LABELS["en"])


def set_locale(locale: str | None) -> str:
    """Cambia el catálogo completo sin reconstruir datos GTFS ni sus índices."""
    global _ACTIVE_LOCALE
    selected = _normalise_locale(locale)
    try:
        selected_messages = _catalog(selected)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        selected = "en"
        selected_messages = _ENGLISH_MESSAGES
    MESSAGES.clear()
    MESSAGES.update(selected_messages)
    _ACTIVE_LOCALE = selected
    return selected


def t(key: str, /, **parameters: object) -> str:
    """Devuelve un texto traducido y falla temprano ante una clave olvidada."""
    try:
        return MESSAGES[key].format(**parameters)
    except KeyError as error:
        raise KeyError(f"Falta la clave i18n: {key}") from error


def pseudo_localize(text: str) -> str:
    """Alarga texto visible para detectar recortes sin simular una traducción real."""
    table = str.maketrans("aeiouAEIOU", "àëïõüÀËÏÕÜ")
    return f"［{text.translate(table)} ~~~］"
