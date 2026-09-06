"""Pruebas focales de validación local/impactada del borrador."""

from gtfs_explorer.domain.changesets import EditorCommand, EditorCommandKind, WorkingCopy
from gtfs_explorer.domain.edit_validation import ValidationImpact, WorkingCopyValidator


def test_validator_reports_new_orphans_and_geometry_errors() -> None:
    working_copy = WorkingCopy(
        {
            ("gtfs_routes", "R1"): {"route_id": "R1", "agency_id": "MISSING"},
            ("gtfs_stops", "S1"): {"stop_id": "S1", "stop_lat": 95.0, "stop_lon": 0.0},
        }
    )
    issues = WorkingCopyValidator().validate(working_copy)
    codes = {issue.rule_code for issue in issues}
    assert "GTFS_EDITOR_ORPHAN_REFERENCE" in codes
    assert "GTFS_EDITOR_COORDINATE_RANGE" in codes


def test_impacted_validation_is_scoped_to_command_impact() -> None:
    working_copy = WorkingCopy(
        {
            ("gtfs_stops", "S1"): {"stop_id": "S1", "stop_lat": 95.0, "stop_lon": 0.0},
            ("gtfs_stops", "S2"): {"stop_id": "S2", "stop_lat": 96.0, "stop_lon": 0.0},
        }
    )
    command = EditorCommand(
        EditorCommandKind.UPDATE_STOP,
        ("gtfs_stops", "S1"),
        working_copy.get(("gtfs_stops", "S1")),
        working_copy.get(("gtfs_stops", "S1")),
    )
    analysis = working_copy.analyze_impact(command)
    impact = ValidationImpact.from_analysis(analysis, command.command_id)
    issues = WorkingCopyValidator().validate(working_copy, impact=impact)
    assert {issue.entity.entity_id for issue in issues if issue.entity is not None} == {"S1"}
