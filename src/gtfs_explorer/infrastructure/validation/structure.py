"""Reglas de estructura derivadas del registro GTFS Schedule versionado."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from gtfs_explorer.domain.source import (
    InputSourceKind,
    SourceEntry,
    SourceEntryState,
    SourceManifest,
)
from gtfs_explorer.domain.spec import FileSpec, ScheduleSpec
from gtfs_explorer.domain.validation import (
    LocalizedMessage,
    ValidationCategory,
    ValidationContext,
    ValidationIssue,
    ValidationSeverity,
)

_STRUCTURE_RULE_CODE = "GTFS_STRUCTURE_2026_04_27"
_COMPATIBLE_RULE_CODE = "GTFS_COMPATIBLE_INPUT_NOT_OFFICIAL"
_UNKNOWN_FILE_RULE_CODE = "GTFS_UNKNOWN_FILE"
_DUPLICATE_FILE_RULE_CODE = "GTFS_DUPLICATE_LOGICAL_FILE"
_DUPLICATE_HEADER_RULE_CODE = "GTFS_DUPLICATE_HEADER"
_EXTRA_HEADER_RULE_CODE = "GTFS_EXTRA_HEADER"


@dataclass(frozen=True)
class StructureValidationRule:
    """Comprueba el contenedor y las cabeceras sin interpretar valores de filas."""

    manifest: SourceManifest
    source_directory: Path
    specification: ScheduleSpec

    code: str = _STRUCTURE_RULE_CODE
    severity: ValidationSeverity = ValidationSeverity.ERROR
    category: ValidationCategory = ValidationCategory.SCHEMA

    def evaluate(self, _context: ValidationContext) -> Iterable[ValidationIssue]:
        entries = {entry.original_name: entry for entry in self.manifest.entries}
        yield from self._mode_issue()
        yield from self._container_issues(entries)
        yield from self._file_presence_issues(entries)
        for filename, file_spec in self.specification.files.items():
            if filename in entries:
                yield from self._header_issues(filename, file_spec)

    def _mode_issue(self) -> Iterable[ValidationIssue]:
        if self.manifest.source_kind is InputSourceKind.FILE:
            yield _issue(
                _COMPATIBLE_RULE_CODE,
                ValidationSeverity.NOTICE,
                "validation.compatible_input_not_official",
                source=self.specification.source["url"],
            )

    def _container_issues(self, entries: Mapping[str, SourceEntry]) -> Iterable[ValidationIssue]:
        for entry in self.manifest.entries:
            if entry.state is SourceEntryState.DUPLICATE_LOGICAL_NAME:
                yield _issue(
                    _DUPLICATE_FILE_RULE_CODE,
                    ValidationSeverity.ERROR,
                    "validation.duplicate_logical_file",
                    file_name=entry.original_name,
                    source=self.specification.source["url"],
                )
            if entry.original_name not in self.specification.files:
                yield _issue(
                    _UNKNOWN_FILE_RULE_CODE,
                    ValidationSeverity.NOTICE,
                    "validation.unknown_file",
                    file_name=entry.original_name,
                    source=self.specification.source["url"],
                )

    def _file_presence_issues(
        self, entries: Mapping[str, SourceEntry]
    ) -> Iterable[ValidationIssue]:
        names = set(entries)
        for filename, file_spec in self.specification.files.items():
            if filename in names:
                continue
            if _is_required_file(filename, file_spec, names):
                yield _issue(
                    file_spec.rule_id,
                    ValidationSeverity.ERROR,
                    "validation.required_file_missing",
                    file_name=filename,
                    source=file_spec.source,
                )

    def _header_issues(self, filename: str, file_spec: FileSpec) -> Iterable[ValidationIssue]:
        header = _read_header(self.source_directory / filename)
        seen: set[str] = set()
        for column in header:
            if column in seen:
                yield _issue(
                    _DUPLICATE_HEADER_RULE_CODE,
                    ValidationSeverity.ERROR,
                    "validation.duplicate_header",
                    file_name=filename,
                    field_name=column,
                    source=file_spec.source,
                )
            seen.add(column)
        for column in header:
            if column not in file_spec.fields:
                yield _issue(
                    _EXTRA_HEADER_RULE_CODE,
                    ValidationSeverity.NOTICE,
                    "validation.extra_header",
                    file_name=filename,
                    field_name=column,
                    source=file_spec.source,
                )
        for field_name, field_spec in file_spec.fields.items():
            if field_name not in seen and field_spec.presence == "required":
                yield _issue(
                    field_spec.rule_id,
                    ValidationSeverity.ERROR,
                    "validation.required_header_missing",
                    file_name=filename,
                    field_name=field_name,
                    source=field_spec.source,
                )


def _is_required_file(filename: str, file_spec: FileSpec, names: set[str]) -> bool:
    if file_spec.presence == "required":
        return True
    if filename == "calendar_dates.txt":
        return "calendar.txt" not in names
    if filename == "feed_info.txt":
        return "translations.txt" in names
    if filename == "levels.txt":
        return False
    if filename == "stops.txt":
        return "locations.geojson" not in names
    return False


def _read_header(path: Path) -> tuple[str, ...]:
    contents = path.read_bytes()
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"Cabecera GTFS no UTF-8: {path.name}") from error
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=",", strict=True)
        header = tuple(next(reader))
    except (StopIteration, csv.Error) as error:
        raise ValueError(f"Cabecera GTFS inválida: {path.name}") from error
    if not header or any(not value for value in header):
        raise ValueError(f"Cabecera GTFS ausente o vacía: {path.name}")
    return header


def _issue(
    rule_code: str,
    severity: ValidationSeverity,
    message_key: str,
    *,
    source: str,
    file_name: str | None = None,
    field_name: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        rule_code=rule_code,
        severity=severity,
        category=ValidationCategory.SCHEMA,
        message=LocalizedMessage(message_key, {"source": source}),
        file_name=file_name,
        field_name=field_name,
    )
