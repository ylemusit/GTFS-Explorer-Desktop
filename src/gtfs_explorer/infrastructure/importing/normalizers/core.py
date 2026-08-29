"""Normalización transaccional y trazable de los archivos GTFS core."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from gtfs_explorer.domain.route_types import is_known_extended_route_type
from gtfs_explorer.domain.spec import FieldSpec, ScheduleSpec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection, ProjectDatabase

_CORE_FILES = (
    "agency.txt",
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
    "calendar.txt",
    "calendar_dates.txt",
)
_TABLES = {filename: "gtfs_" + filename.removesuffix(".txt") for filename in _CORE_FILES}
_INTEGER = re.compile(r"[0-9]+")
_ENUM_INTEGER = re.compile(r"-?[0-9]+")
_TIME = re.compile(r"[0-9]{2,}:[0-5][0-9]:[0-5][0-9]")


@dataclass(frozen=True)
class CoreNormalizationResult:
    """Recuentos de filas normalizadas y problemas detectados."""

    row_counts: dict[str, int]
    issue_count: int


class CoreNormalizer:
    """Convierte staging core sin perder lexemas ni ocultar conversiones fallidas."""

    def normalize(
        self,
        database: ProjectDatabase,
        specification: ScheduleSpec,
        *,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> CoreNormalizationResult:
        """Sustituye el modelo core y sus problemas en una única transacción."""
        row_counts: dict[str, int] = {}
        issues: list[tuple[object, ...]] = []
        with database.connection() as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                for table_name in (*_TABLES.values(), "normalization_issues"):
                    connection.execute(f"DELETE FROM {table_name}")
                present = self._present_files(connection)
                self._record_missing_file_issues(present, issues)
                for filename in _CORE_FILES:
                    _raise_if_cancelled(is_cancelled)
                    if filename not in present:
                        continue
                    count = self._normalize_file(
                        connection, filename, specification, issues, is_cancelled
                    )
                    row_counts[filename] = count
                if issues:
                    connection.executemany(
                        "INSERT INTO normalization_issues VALUES (?, ?, ?, ?, ?, ?, ?)", issues
                    )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return CoreNormalizationResult(row_counts, len(issues))

    @staticmethod
    def _present_files(connection: DatabaseConnection) -> set[str]:
        rows = connection.execute(
            "SELECT original_name FROM stg_source_inventory WHERE known_to_schedule_spec"
        ).fetchall()
        return {str(row[0]) for row in rows}

    @staticmethod
    def _record_missing_file_issues(present: set[str], issues: list[tuple[object, ...]]) -> None:
        for filename in ("agency.txt", "routes.txt", "trips.txt", "stop_times.txt"):
            if filename not in present:
                issues.append(
                    (
                        "GTFS_REQUIRED_FILE_MISSING",
                        "ERROR",
                        filename,
                        None,
                        None,
                        None,
                        "Falta un archivo core obligatorio.",
                    )
                )
        if "calendar.txt" not in present and "calendar_dates.txt" not in present:
            issues.append(
                (
                    "GTFS_SERVICE_DATES_MISSING",
                    "ERROR",
                    "calendar.txt",
                    None,
                    None,
                    None,
                    "Se requiere calendar.txt o calendar_dates.txt "
                    "para definir fechas de servicio.",
                )
            )
        if "calendar.txt" not in present and "calendar_dates.txt" in present:
            return
        if "calendar.txt" in present and "calendar_dates.txt" not in present:
            return

    def _normalize_file(
        self,
        connection: DatabaseConnection,
        filename: str,
        specification: ScheduleSpec,
        issues: list[tuple[object, ...]],
        is_cancelled: Callable[[], bool],
    ) -> int:
        fields = specification.files[filename].fields
        rows = connection.execute(f"SELECT * FROM stg_{filename.removesuffix('.txt')}").fetchall()
        columns = [
            str(item[0])
            for item in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [f"stg_{filename.removesuffix('.txt')}"],
            ).fetchall()
        ]
        count = 0
        for row in rows:
            if count % 128 == 0:
                _raise_if_cancelled(is_cancelled)
            raw = dict(zip(columns, row, strict=True))
            source_row = int(raw.pop("source_row"))
            source_filename = str(raw.pop("source_filename"))
            raw.pop("extra_columns")
            values = self._typed_values(filename, source_row, raw, fields, specification, issues)
            insert_columns, insert_values = _insert_row(
                filename, source_filename, source_row, raw, values
            )
            placeholders = ", ".join("?" for _ in insert_values)
            statement = (
                f"INSERT INTO {_TABLES[filename]} "
                f"({', '.join(insert_columns)}) VALUES ({placeholders})"
            )
            connection.execute(statement, insert_values)
            count += 1
        return count

    @staticmethod
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
                values[field_name] = _convert(
                    lexeme,
                    field,
                    specification,
                    allow_known_extended_route_type=(
                        filename == "routes.txt" and field_name == "route_type"
                    ),
                )
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


def _raise_if_cancelled(is_cancelled: Callable[[], bool]) -> None:
    if is_cancelled():
        from gtfs_explorer.domain.errors import ImportCancelled

        raise ImportCancelled("La normalización se ha cancelado.")


def _convert(
    lexeme: str,
    field: FieldSpec,
    specification: ScheduleSpec,
    *,
    allow_known_extended_route_type: bool = False,
) -> object:
    value_type = field.value_type
    if value_type == "Time":
        if _TIME.fullmatch(lexeme) is None:
            raise ValueError("La hora GTFS debe tener formato HH:MM:SS válido.")
        hours, minutes, seconds = (int(value) for value in lexeme.split(":"))
        return hours * 3600 + minutes * 60 + seconds
    if value_type == "Date":
        if re.fullmatch(r"[0-9]{8}", lexeme) is None:
            raise ValueError("La fecha GTFS debe tener formato YYYYMMDD válido.")
        try:
            return datetime.strptime(lexeme, "%Y%m%d").date()
        except ValueError as error:
            raise ValueError("La fecha GTFS no es válida.") from error
    if value_type in {"Non-negative integer"}:
        if _INTEGER.fullmatch(lexeme) is None:
            raise ValueError("El entero no negativo no es válido.")
        return int(lexeme)
    if value_type in {"Float", "Non-negative float", "Latitude", "Longitude"}:
        try:
            converted = float(lexeme)
        except ValueError as error:
            raise ValueError("El número decimal no es válido.") from error
        if not math.isfinite(converted) or (value_type == "Non-negative float" and converted < 0):
            raise ValueError("El número decimal no está dentro del dominio permitido.")
        return converted
    if value_type == "Enum":
        if _ENUM_INTEGER.fullmatch(lexeme) is None:
            raise ValueError("La enumeración debe ser un entero.")
        if (
            field.enum is not None
            and specification.enums[field.enum]
            and lexeme not in specification.enums[field.enum]
            and not (allow_known_extended_route_type and is_known_extended_route_type(lexeme))
        ):
            raise ValueError("El valor no pertenece a la enumeración GTFS.")
        return int(lexeme)
    return lexeme


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
        if _is_time_or_date(filename, field_name):
            columns.extend([f"{field_name}_lexeme", _typed_column(field_name)])
            row.extend([raw[field_name], value])
        else:
            columns.append(field_name)
            row.append(value)
    return columns, row


def _is_time_or_date(filename: str, field_name: str) -> bool:
    return (
        filename == "stop_times.txt"
        and field_name
        in {
            "arrival_time",
            "departure_time",
            "start_pickup_drop_off_window",
            "end_pickup_drop_off_window",
        }
        or filename in {"calendar.txt", "calendar_dates.txt"}
        and field_name
        in {
            "start_date",
            "end_date",
            "date",
        }
    )


def _typed_column(field_name: str) -> str:
    if field_name in {"start_date", "end_date", "date"}:
        return field_name
    if field_name == "arrival_time":
        return "arrival_service_seconds"
    if field_name == "departure_time":
        return "departure_service_seconds"
    return f"{field_name}_service_seconds"
