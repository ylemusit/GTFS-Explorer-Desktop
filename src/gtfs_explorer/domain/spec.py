"""Carga y validación del registro versionado de GTFS Schedule."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PRESENCES = frozenset(
    {
        "required",
        "optional",
        "conditionally_required",
        "conditionally_forbidden",
        "recommended",
    }
)


@dataclass(frozen=True)
class FieldSpec:
    presence: str
    value_type: str
    rule_id: str
    source: str
    references: tuple[str, ...]
    enum: str | None
    condition: str | None


@dataclass(frozen=True)
class FileSpec:
    presence: str
    rule_id: str
    source: str
    condition: str | None
    fields: dict[str, FieldSpec]


@dataclass(frozen=True)
class ScheduleSpec:
    revision: str
    source: dict[str, str]
    files: dict[str, FileSpec]
    enums: dict[str, tuple[str, ...]]


def _require_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} debe ser texto no vacío.")
    return value


def _require_presence(value: object, context: str) -> str:
    presence = _require_string(value, context)
    if presence not in PRESENCES:
        raise ValueError(f"Presencia inválida en {context}: {presence}.")
    return presence


def load_schedule_spec(path: Path) -> ScheduleSpec:
    """Carga un registro y comprueba sus invariantes antes de exponerlo."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"revision", "source", "files", "enums"}:
        raise ValueError("Registro GTFS inválido.")

    revision = _require_string(payload["revision"], "revision")
    source_payload = payload["source"]
    if not isinstance(source_payload, dict) or set(source_payload) != {
        "url",
        "revised",
        "sha256",
    }:
        raise ValueError("Fuente GTFS inválida.")
    source = {key: _require_string(value, f"source.{key}") for key, value in source_payload.items()}
    if source["revised"] != revision or len(source["sha256"]) != 64:
        raise ValueError("La revisión o hash de la fuente GTFS es inválido.")

    raw_enums = payload["enums"]
    if not isinstance(raw_enums, dict):
        raise ValueError("Enums GTFS inválidos.")
    enums: dict[str, tuple[str, ...]] = {}
    for name, values in raw_enums.items():
        enum_name = _require_string(name, "nombre de enum")
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError(f"Valores inválidos para enum {enum_name}.")
        enums[enum_name] = tuple(values)

    raw_files = payload["files"]
    if not isinstance(raw_files, dict) or not raw_files:
        raise ValueError("Archivos GTFS inválidos.")
    rule_ids: set[str] = set()
    files: dict[str, FileSpec] = {}
    for filename, raw_file in raw_files.items():
        filename = _require_string(filename, "nombre de archivo")
        if not isinstance(raw_file, dict) or set(raw_file) != {
            "presence",
            "rule_id",
            "source",
            "condition",
            "fields",
        }:
            raise ValueError(f"Registro de archivo inválido: {filename}.")
        file_rule_id = _require_string(raw_file["rule_id"], f"regla de {filename}")
        if file_rule_id in rule_ids:
            raise ValueError(f"ID de regla duplicado: {file_rule_id}")
        rule_ids.add(file_rule_id)
        raw_fields = raw_file["fields"]
        if not isinstance(raw_fields, dict) or not raw_fields:
            raise ValueError(f"Campos inválidos en {filename}.")
        fields: dict[str, FieldSpec] = {}
        for field, raw_field in raw_fields.items():
            field = _require_string(field, f"campo de {filename}")
            if not isinstance(raw_field, dict) or set(raw_field) != {
                "presence",
                "type",
                "rule_id",
                "source",
                "references",
                "enum",
                "condition",
            }:
                raise ValueError(f"Registro de campo inválido: {filename}.{field}.")
            field_rule_id = _require_string(raw_field["rule_id"], f"regla de {filename}.{field}")
            if field_rule_id in rule_ids:
                raise ValueError(f"ID de regla duplicado: {field_rule_id}")
            rule_ids.add(field_rule_id)
            references = raw_field["references"]
            if not isinstance(references, list) or any(
                not isinstance(item, str) for item in references
            ):
                raise ValueError(f"Referencias inválidas en {filename}.{field}.")
            enum = raw_field["enum"]
            if enum is not None and (not isinstance(enum, str) or enum not in enums):
                raise ValueError(f"Enum inválido en {filename}.{field}.")
            condition = raw_field["condition"]
            if condition is not None and not isinstance(condition, str):
                raise ValueError(f"Condición inválida en {filename}.{field}.")
            fields[field] = FieldSpec(
                _require_presence(raw_field["presence"], f"{filename}.{field}"),
                _require_string(raw_field["type"], f"tipo de {filename}.{field}"),
                field_rule_id,
                _require_string(raw_field["source"], f"fuente de {filename}.{field}"),
                tuple(references),
                enum,
                condition,
            )
        file_condition = raw_file["condition"]
        if file_condition is not None and not isinstance(file_condition, str):
            raise ValueError(f"Condición inválida en {filename}.")
        files[filename] = FileSpec(
            _require_presence(raw_file["presence"], filename),
            file_rule_id,
            _require_string(raw_file["source"], f"fuente de {filename}"),
            file_condition,
            fields,
        )
    return ScheduleSpec(revision, source, files, enums)
