"""Validación por conjuntos de referencias GTFS sobre las tablas de staging."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from gtfs_explorer.domain.spec import FieldSpec, ScheduleSpec
from gtfs_explorer.domain.validation import (
    LocalizedMessage,
    ValidationCategory,
    ValidationContext,
    ValidationEntity,
    ValidationIssue,
    ValidationSeverity,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection
from gtfs_explorer.infrastructure.validation.fields import (
    _quote,
    _staging_table,
    _table_columns,
    _table_exists,
)


@dataclass(frozen=True)
class ReferenceValidationRule:
    """Detecta claves foráneas ausentes mediante una consulta por relación, no por fila."""

    connection: DatabaseConnection
    specification: ScheduleSpec
    code: str = "GTFS_REFERENCES_2026_04_27"
    severity: ValidationSeverity = ValidationSeverity.ERROR
    category: ValidationCategory = ValidationCategory.REFERENCE

    def evaluate(self, _context: ValidationContext) -> Iterable[ValidationIssue]:
        for filename, file_spec in self.specification.files.items():
            source_table = _staging_table(filename)
            if not _table_exists(self.connection, source_table):
                continue
            source_columns = _table_columns(self.connection, source_table)
            for field_name, field_spec in file_spec.fields.items():
                if not field_spec.references or field_name not in source_columns:
                    continue
                targets = _available_targets(self.connection, field_spec)
                if filename == "calendar_dates.txt" and field_name == "service_id":
                    targets = (*targets, (source_table, field_name))
                if not targets:
                    continue
                clauses = " OR ".join(
                    "EXISTS (SELECT 1 FROM "
                    f"{_quote(table)} target WHERE target.{_quote(column)} "
                    f"= source.{_quote(field_name)})"
                    for table, column in targets
                )
                rows = self.connection.execute(
                    "SELECT source.source_row, "
                    f"source.{_quote(field_name)} FROM {_quote(source_table)} source "
                    f"WHERE source.{_quote(field_name)} IS NOT NULL "
                    f"AND source.{_quote(field_name)} <> '' "
                    f"AND NOT ({clauses})"
                ).fetchall()
                for source_row, value in rows:
                    reference = ", ".join(field_spec.references)
                    yield ValidationIssue(
                        rule_code=field_spec.rule_id,
                        severity=ValidationSeverity.ERROR,
                        category=ValidationCategory.REFERENCE,
                        message=LocalizedMessage(
                            "validation.reference_missing",
                            {
                                "source": field_spec.source,
                                "reference": reference,
                                "value": str(value),
                            },
                        ),
                        file_name=filename,
                        row_number=int(source_row),
                        field_name=field_name,
                        entity=ValidationEntity(filename.removesuffix(".txt"), str(value)),
                    )


def _available_targets(
    connection: DatabaseConnection, field: FieldSpec
) -> tuple[tuple[str, str], ...]:
    targets: list[tuple[str, str]] = []
    for reference in field.references:
        if "." not in reference or reference.endswith(".geojson"):
            continue
        table_name, column = reference.rsplit(".", 1)
        table = _staging_table(table_name + ".txt")
        if _table_exists(connection, table) and column in _table_columns(connection, table):
            targets.append((table, column))
    return tuple(targets)
