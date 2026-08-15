from __future__ import annotations

from pathlib import Path

from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import FieldSpec, FileSpec, ScheduleSpec
from gtfs_explorer.domain.validation import (
    ValidationContext,
    ValidationIssue,
    ValidationSeverity,
)
from gtfs_explorer.infrastructure.importing.directory_source import DirectorySource
from gtfs_explorer.infrastructure.validation.structure import StructureValidationRule


def _spec() -> ScheduleSpec:
    fields = {
        "id": FieldSpec(
            "required", "ID", "ID_REQUIRED", "https://example.test/table", (), None, None
        ),
        "name": FieldSpec(
            "required", "Text", "NAME_REQUIRED", "https://example.test/table", (), None, None
        ),
    }
    return ScheduleSpec(
        "test",
        {"url": "https://example.test/reference"},
        {
            "required.txt": FileSpec(
                "required", "FILE_REQUIRED", "https://example.test/table", None, fields
            )
        },
        {},
    )


def _issues(
    source: Path, kind: InputSourceKind = InputSourceKind.DIRECTORY
) -> tuple[ValidationIssue, ...]:
    manifest = DirectorySource().inventory(InputSource(source, kind))
    return tuple(
        StructureValidationRule(manifest, source, _spec()).evaluate(
            ValidationContext("feed", "batch")
        )
    )


def test_structure_reports_required_file_with_spec_rule_and_source(tmp_path: Path) -> None:
    issues = _issues(tmp_path)

    assert [(issue.rule_code, issue.message.parameters["source"]) for issue in issues] == [
        ("FILE_REQUIRED", "https://example.test/table")
    ]


def test_structure_reports_required_headers_duplicates_and_extras(tmp_path: Path) -> None:
    (tmp_path / "required.txt").write_text("id,id,extra\n1,2,x\n", encoding="utf-8")

    issues = _issues(tmp_path)

    assert [(issue.rule_code, issue.field_name, issue.severity) for issue in issues] == [
        ("GTFS_DUPLICATE_HEADER", "id", ValidationSeverity.ERROR),
        ("GTFS_EXTRA_HEADER", "extra", ValidationSeverity.NOTICE),
        ("NAME_REQUIRED", "name", ValidationSeverity.ERROR),
    ]
    assert all(issue.message.parameters["source"] for issue in issues)


def test_structure_separates_compatible_input_from_official_gtfs(tmp_path: Path) -> None:
    source = tmp_path / "partial.csv"
    source.write_text("id,name\n1,North\n", encoding="utf-8")

    issues = _issues(source, InputSourceKind.FILE)

    assert [(issue.rule_code, issue.severity) for issue in issues] == [
        ("GTFS_COMPATIBLE_INPUT_NOT_OFFICIAL", ValidationSeverity.NOTICE),
        ("GTFS_UNKNOWN_FILE", ValidationSeverity.NOTICE),
        ("FILE_REQUIRED", ValidationSeverity.ERROR),
    ]
