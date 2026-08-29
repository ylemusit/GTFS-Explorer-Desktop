"""Reglas por campo derivadas del registro GTFS y ejecutadas sobre staging fiel."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from gtfs_explorer.domain.route_types import is_known_extended_route_type
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

_TIME = re.compile(r"[0-9]{2,}:[0-5][0-9]:[0-5][0-9]")
_INTEGER = re.compile(r"-?[0-9]+")
_NON_NEGATIVE_INTEGER = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class FieldValidationRule:
    """Comprueba presencia, conversión, rangos y dominios sin perder la fila fuente."""

    connection: DatabaseConnection
    specification: ScheduleSpec
    code: str = "GTFS_FIELDS_2026_04_27"
    severity: ValidationSeverity = ValidationSeverity.ERROR
    category: ValidationCategory = ValidationCategory.FIELD

    def evaluate(self, _context: ValidationContext) -> Iterable[ValidationIssue]:
        for filename, file_spec in self.specification.files.items():
            table = _staging_table(filename)
            if not _table_exists(self.connection, table):
                continue
            columns = _table_columns(self.connection, table)
            for field_name, field_spec in file_spec.fields.items():
                if field_name not in columns:
                    continue
                rows = self.connection.execute(
                    f"SELECT source_row, {_quote(field_name)} FROM {_quote(table)}"
                ).fetchall()
                for source_row, raw_value in rows:
                    value = "" if raw_value is None else str(raw_value)
                    if not value:
                        if field_spec.presence == "required":
                            yield _issue(
                                field_spec,
                                "validation.required_value_missing",
                                filename,
                                int(source_row),
                                field_name,
                                value,
                            )
                        continue
                    message_key = _invalid_value_message(
                        value,
                        field_spec,
                        self.specification,
                        filename=filename,
                        field_name=field_name,
                    )
                    if message_key is not None:
                        yield _issue(
                            field_spec, message_key, filename, int(source_row), field_name, value
                        )


def _invalid_value_message(
    value: str,
    field: FieldSpec,
    specification: ScheduleSpec,
    *,
    filename: str | None = None,
    field_name: str | None = None,
) -> str | None:
    if (
        field.enum is not None
        and specification.enums[field.enum]
        and value not in specification.enums[field.enum]
        and not (
            filename == "routes.txt"
            and field_name == "route_type"
            and is_known_extended_route_type(value)
        )
    ):
        return "validation.enum_value_invalid"
    value_type = field.value_type
    if value_type == "Time":
        return None if _TIME.fullmatch(value) else "validation.time_value_invalid"
    if value_type == "Date":
        if re.fullmatch(r"[0-9]{8}", value) is None:
            return "validation.date_value_invalid"
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError:
            return "validation.date_value_invalid"
        return None
    if value_type in {"Integer", "Non-null integer", "Non-zero integer"}:
        if _INTEGER.fullmatch(value) is None:
            return "validation.integer_value_invalid"
        if value_type == "Non-zero integer" and int(value) == 0:
            return "validation.integer_value_invalid"
        return None
    if value_type in {"Non-negative integer", "Positive integer"}:
        if _NON_NEGATIVE_INTEGER.fullmatch(value) is None:
            return "validation.integer_value_invalid"
        if value_type == "Positive integer" and int(value) == 0:
            return "validation.integer_value_invalid"
        return None
    if value_type in {
        "Float",
        "Non-negative float",
        "Positive float",
        "Latitude",
        "Longitude",
    }:
        try:
            number = float(value)
        except ValueError:
            return "validation.number_value_invalid"
        if not math.isfinite(number):
            return "validation.number_value_invalid"
        if value_type == "Non-negative float" and number < 0:
            return "validation.number_value_invalid"
        if value_type == "Positive float" and number <= 0:
            return "validation.number_value_invalid"
        if value_type == "Latitude" and not -90 <= number <= 90:
            return "validation.coordinate_value_invalid"
        if value_type == "Longitude" and not -180 <= number <= 180:
            return "validation.coordinate_value_invalid"
    return None


def _issue(
    field: FieldSpec, message_key: str, filename: str, row_number: int, field_name: str, value: str
) -> ValidationIssue:
    return ValidationIssue(
        rule_code=field.rule_id,
        severity=ValidationSeverity.ERROR,
        category=ValidationCategory.FIELD,
        message=LocalizedMessage(message_key, {"source": field.source, "value": value}),
        file_name=filename,
        row_number=row_number,
        field_name=field_name,
        entity=ValidationEntity(filename.removesuffix(".txt"), value),
    )


def _staging_table(filename: str) -> str:
    return "stg_" + filename.removesuffix(".txt").casefold()


def _table_exists(connection: DatabaseConnection, table: str) -> bool:
    row = connection.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone()
    assert row is not None
    return int(row[0]) == 1


def _table_columns(connection: DatabaseConnection, table: str) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]
        ).fetchall()
    }


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
