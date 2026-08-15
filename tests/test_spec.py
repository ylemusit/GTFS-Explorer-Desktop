from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from gtfs_explorer.domain.spec import load_schedule_spec

SPEC_PATH = Path("schemas/gtfs_schedule/2026-04-27/spec.json")
SNAPSHOT_PATH = Path("tests/fixtures/snapshots/gtfs_schedule_2026-04-27.snapshot.json")


def test_schedule_spec_matches_controlled_2026_04_27_snapshot() -> None:
    specification = load_schedule_spec(SPEC_PATH)
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    projection = {name: list(file_spec.fields) for name, file_spec in specification.files.items()}
    field_names_hash = hashlib.sha256(
        json.dumps(projection, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()

    assert specification.revision == "2026-04-27"
    assert specification.source["revised"] == specification.revision
    assert len(specification.files) == snapshot["file_count"]
    assert (
        sum(len(file_spec.fields) for file_spec in specification.files.values())
        == snapshot["field_count"]
    )
    assert field_names_hash == snapshot["field_names_sha256"]


def test_schedule_spec_records_conditions_enums_references_and_stable_sources() -> None:
    specification = load_schedule_spec(SPEC_PATH)
    booking_rule = specification.files["booking_rules.txt"].fields["prior_notice_duration_min"]
    trip_route = specification.files["trips.txt"].fields["route_id"]
    route_type = specification.files["routes.txt"].fields["route_type"]

    assert specification.files["calendar.txt"].condition == (
        "required unless all service dates are in calendar_dates.txt"
    )
    assert booking_rule.presence == "conditionally_required"
    assert booking_rule.condition is not None
    assert trip_route.references == ("routes.route_id",)
    assert route_type.enum == "GTFS_ENUM_ROUTES_TXT_ROUTE_TYPE"
    assert route_type.enum in specification.enums
    assert (
        booking_rule.rule_id
        == "GTFS_BOOKING_RULES_TXT_PRIOR_NOTICE_DURATION_MIN_CONDITIONALLY_REQUIRED"
    )
    assert booking_rule.source.startswith("https://gtfs.org/documentation/schedule/reference/#")


class PayloadPath:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def read_text(self, *, encoding: str) -> str:
        assert encoding == "utf-8"
        return json.dumps(self.payload)


def test_schedule_spec_rejects_duplicate_rule_id() -> None:
    payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    payload["files"]["agency.txt"]["fields"]["agency_name"]["rule_id"] = payload["files"][
        "agency.txt"
    ]["rule_id"]
    with pytest.raises(ValueError, match="ID de regla duplicado"):
        load_schedule_spec(PayloadPath(payload))  # type: ignore[arg-type]
