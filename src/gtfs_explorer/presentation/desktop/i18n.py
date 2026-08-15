"""Traducción local con comprobación explícita de claves y pseudo-localización."""

from __future__ import annotations

import json
from importlib.resources import files


def _messages() -> dict[str, str]:
    payload = json.loads(
        files("gtfs_explorer.resources.i18n").joinpath("es.json").read_text("utf-8")
    )
    messages = payload.get("messages")
    if not isinstance(messages, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in messages.items()
    ):
        raise ValueError("El catálogo español de interfaz no es válido.")
    return messages


MESSAGES = _messages()


def t(key: str, /, **parameters: object) -> str:
    """Devuelve el texto español o falla temprano ante una clave olvidada."""
    try:
        return MESSAGES[key].format(**parameters)
    except KeyError as error:
        raise KeyError(f"Falta la clave i18n: {key}") from error


def pseudo_localize(text: str) -> str:
    """Alarga texto visible para detectar recortes sin simular una traducción real."""
    table = str.maketrans("aeiouAEIOU", "àëïõüÀËÏÕÜ")
    return f"［{text.translate(table)} ~~~］"
