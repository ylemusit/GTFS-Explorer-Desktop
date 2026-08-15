"""Genera el registro propio desde el snapshot oficial de esta revisión."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


REVISION = "2026-04-27"
SOURCE_URL = "https://gtfs.org/documentation/schedule/reference/"
SOURCE_ANCHOR = "https://gtfs.org/documentation/schedule/reference/#"
FILE_CONDITIONS = {
    "stops.txt": "required unless locations.geojson defines demand-responsive zones",
    "calendar.txt": "required unless all service dates are in calendar_dates.txt",
    "calendar_dates.txt": "required when calendar.txt is omitted",
    "networks.txt": "forbidden when routes.txt contains network_id",
    "route_networks.txt": "forbidden when routes.txt contains network_id",
    "levels.txt": "required when pathways.txt contains pathway_mode=5",
    "feed_info.txt": "required when translations.txt is provided",
}


def slug(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def presence(value: str) -> str:
    return {
        "Required": "required",
        "Optional": "optional",
        "Conditionally Required": "conditionally_required",
        "Conditionally Forbidden": "conditionally_forbidden",
        "Recommended": "recommended",
    }[re.sub(r"[*]", "", value).strip()]


def parse_table_row(row: str) -> tuple[str, str, str, str]:
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    if len(cells) != 4:
        raise ValueError(f"Fila oficial no soportada: {row}")
    field = re.search(r"`([^`]+)`", cells[0])
    if field is None:
        raise ValueError(f"Campo oficial no soportado: {cells[0]}")
    return field.group(1), cells[1], cells[2], cells[3]


def parse_reference(text: str) -> dict[str, object]:
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if "**Revised April 27, 2026." not in text:
        raise ValueError("El snapshot no corresponde a la revisión 2026-04-27.")
    files: dict[str, object] = {}
    enums: dict[str, list[str]] = {}
    sections = re.split(r"^### ", text, flags=re.MULTILINE)[1:]
    for section in sections:
        filename, _, body = section.partition("\n")
        if not filename.endswith((".txt", ".geojson")):
            continue
        file_presence = re.search(r"^File: (?:\*\*)?(.+?)(?:\*\*)?$", body, re.MULTILINE)
        if file_presence is None:
            raise ValueError(f"No se encontró presencia para {filename}.")
        anchor = filename.replace("_", "").replace(".", "")
        fields: dict[str, object] = {}
        for line in body.splitlines():
            if not line.startswith("|") or "`" not in line:
                continue
            field, field_type, field_presence, description = parse_table_row(line)
            field_anchor = f"{SOURCE_ANCHOR}{anchor}"
            references = re.findall(r"`([a-z_]+\.[a-z_]+)`", field_type)
            enum_name: str | None = None
            if field_type == "Enum":
                enum_name = f"GTFS_ENUM_{slug(filename)}_{slug(field)}"
                enums[enum_name] = re.findall(r"`([^`]+)`\s*(?:\([^)]*\))?\s*-", description)
            fields[field] = {
                "presence": presence(field_presence),
                "type": field_type,
                "rule_id": f"GTFS_{slug(filename)}_{slug(field)}_{slug(presence(field_presence))}",
                "source": field_anchor,
                "references": references,
                "enum": enum_name,
                "condition": description if "Conditionally" in field_presence else None,
            }
        if not fields:
            raise ValueError(f"No se encontraron campos para {filename}.")
        file_presence_value = presence(file_presence.group(1))
        files[filename] = {
            "presence": file_presence_value,
            "rule_id": f"GTFS_FILE_{slug(filename)}_{slug(file_presence_value)}",
            "source": f"{SOURCE_ANCHOR}{anchor}",
            "condition": FILE_CONDITIONS.get(filename),
            "fields": fields,
        }
    return {
        "revision": REVISION,
        "source": {"url": SOURCE_URL, "revised": REVISION, "sha256": source_hash},
        "files": files,
        "enums": enums,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = parse_reference(args.reference.read_text(encoding="utf-8"))
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
