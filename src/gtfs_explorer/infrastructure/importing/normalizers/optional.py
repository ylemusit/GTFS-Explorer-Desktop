"""Normalización trazable de opcionales GTFS prioritarios."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from gtfs_explorer.domain.errors import ImportCancelled
from gtfs_explorer.domain.spec import FieldSpec, ScheduleSpec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection, ProjectDatabase
from gtfs_explorer.infrastructure.importing.normalizers.core import _convert
from gtfs_explorer.infrastructure.importing.normalizers.geometry import _staging_columns

_FILES = ("frequencies.txt", "transfers.txt", "feed_info.txt", "attributions.txt")
_TABLES = {filename: "gtfs_" + filename.removesuffix(".txt") for filename in _FILES}
_POSITIVE_INTEGER = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class OptionalNormalizationResult:
    """Recuentos de opcionales normalizados y problemas detectados."""

    row_counts: dict[str, int]
    issue_count: int


class OptionalNormalizer:
    """Convierte los opcionales priorizados sin deducir reglas de transferencia."""

    def normalize(
        self,
        database: ProjectDatabase,
        specification: ScheduleSpec,
        *,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> OptionalNormalizationResult:
        """Sustituye los opcionales soportados y sus problemas en una transacción."""
        row_counts: dict[str, int] = {}
        issues: list[tuple[object, ...]] = []
        with database.connection() as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                for table_name in _TABLES.values():
                    connection.execute(f"DELETE FROM {table_name}")
                connection.execute(
                    "DELETE FROM normalization_issues WHERE file_name IN (?, ?, ?, ?)", _FILES
                )
                present = _present_files(connection)
                for filename in _FILES:
                    if filename in present:
                        row_counts[filename] = self._normalize_file(
                            connection, filename, specification, issues, is_cancelled
                        )
                if issues:
                    connection.executemany(
                        "INSERT INTO normalization_issues VALUES (?, ?, ?, ?, ?, ?, ?)", issues
                    )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return OptionalNormalizationResult(row_counts, len(issues))

    def _normalize_file(
        self,
        connection: DatabaseConnection,
        filename: str,
        specification: ScheduleSpec,
        issues: list[tuple[object, ...]],
        is_cancelled: Callable[[], bool],
    ) -> int:
        fields = specification.files[filename].fields
        columns = _staging_columns(connection, filename)
        table_name = "stg_" + filename.removesuffix(".txt")
        rows = connection.execute(f"SELECT * FROM {table_name}").fetchall()
        for index, row in enumerate(rows):
            if index % 128 == 0 and is_cancelled():
                raise ImportCancelled("La normalización se ha cancelado.")
            raw = dict(zip(columns, row, strict=True))
            source_row = int(raw.pop("source_row"))
            source_filename = str(raw.pop("source_filename"))
            raw.pop("extra_columns")
            values = _typed_values(filename, source_row, raw, fields, specification, issues)
            columns_to_insert, values_to_insert = _insert_row(
                filename, source_filename, source_row, raw, values
            )
            placeholders = ", ".join("?" for _ in values_to_insert)
            connection.execute(
                f"INSERT INTO {_TABLES[filename]} ({', '.join(columns_to_insert)}) "
                f"VALUES ({placeholders})",
                values_to_insert,
            )
        return len(rows)


def _present_files(connection: DatabaseConnection) -> set[str]:
    rows = connection.execute(
        "SELECT original_name FROM stg_source_inventory WHERE known_to_schedule_spec"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _typed_values(
    filename: str,
    source_row: int,
    raw: dict[str, object],
    fields: dict[str, FieldSpec],
    specification: ScheduleSpec,
    issues: list[tuple[object, ...]],
) -> dict[str, object]:
    values: dict[str, object] = {}
    for field_name, field in fields.items():
        lexeme = raw[field_name]
        assert lexeme is None or isinstance(lexeme, str)
        if lexeme is None or lexeme == "":
            values[field_name] = None
            if field.presence == "required":
                issues.append(
                    (
                        "GTFS_REQUIRED_VALUE_MISSING",
                        "ERROR",
                        filename,
                        source_row,
                        field_name,
                        lexeme,
                        "Falta un valor obligatorio.",
                    )
                )
            continue
        try:
            values[field_name] = _convert_optional(lexeme, field, specification)
        except ValueError as error:
            values[field_name] = None
            issues.append(
                (
                    "GTFS_TYPE_CONVERSION_INVALID",
                    "ERROR",
                    filename,
                    source_row,
                    field_name,
                    lexeme,
                    str(error),
                )
            )
    return values


def _convert_optional(lexeme: str, field: FieldSpec, specification: ScheduleSpec) -> object:
    if field.value_type == "Positive integer":
        if _POSITIVE_INTEGER.fullmatch(lexeme) is None or int(lexeme) < 1:
            raise ValueError("El entero positivo no es válido.")
        return int(lexeme)
    return _convert(lexeme, field, specification)


def _insert_row(
    filename: str,
    source_filename: str,
    source_row: int,
    raw: dict[str, object],
    values: dict[str, object],
) -> tuple[list[str], list[object]]:
    columns = ["source_filename", "source_row", "raw_values"]
    row: list[object] = [source_filename, source_row, json.dumps(raw, ensure_ascii=False)]
    for field_name, value in values.items():
        if field_name in {"start_time", "end_time"}:
            columns.extend([f"{field_name}_lexeme", f"{field_name}_service_seconds"])
            row.extend([raw[field_name], value])
        elif field_name in {"feed_start_date", "feed_end_date"}:
            columns.extend([f"{field_name}_lexeme", field_name])
            row.extend([raw[field_name], value])
        else:
            columns.append(field_name)
            row.append(value)
    return columns, row
