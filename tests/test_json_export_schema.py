from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "json_export" / "1.0.0" / "gtfs-explorer.bundle.schema.json"
EXAMPLES = SCHEMA_PATH.parent / "examples"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_public_schema_is_a_closed_versioned_contract() -> None:
    schema = _load(SCHEMA_PATH)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("/json-export/1.0.0/gtfs-explorer.bundle.schema.json")
    assert schema["properties"]["schema_version"] == {"const": "1.0.0"}
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "schema_version",
        "generator",
        "source",
        "selection",
        "agencies",
        "routes",
        "services",
        "stops",
        "shapes",
        "trips",
        "transfers",
        "metadata",
        "warnings",
    ]


def test_golden_examples_preserve_public_semantics() -> None:
    minimal = _load(EXAMPLES / "minimal.json")
    complete = _load(EXAMPLES / "complete.json")

    assert minimal["schema_version"] == complete["schema_version"] == "1.0.0"
    assert minimal["generator"]["name"] == complete["generator"]["name"] == "GTFS Explorer Desktop"
    assert complete["trips"][0]["stop_times"][0]["arrival"] == "25:00:00"
    assert complete["trips"][0]["stop_times"][0]["arrival_service_seconds"] == 90_000
    assert set(minimal) == set(complete)


def test_schema_encodes_breaking_contract_boundaries() -> None:
    definitions = _load(SCHEMA_PATH)["$defs"]

    assert definitions["source"]["properties"]["sha256"]["pattern"] == "^[a-f0-9]{64}$"
    assert definitions["time"]["pattern"].startswith("^([0-9]{1,})")
    assert definitions["stop_time"]["properties"]["arrival_service_seconds"]["minimum"] == 0
    assert definitions["trip"]["properties"]["direction_id"]["enum"] == [0, 1, None]
    assert definitions["stop"]["properties"]["latitude"]["maximum"] == 90
    assert definitions["stop"]["properties"]["longitude"]["minimum"] == -180
