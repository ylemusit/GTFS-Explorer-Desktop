"""Normalización trazable de la geometría GTFS soportada."""

from __future__ import annotations

import json
from dataclasses import dataclass

from gtfs_explorer.domain.spec import FieldSpec, ScheduleSpec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection, ProjectDatabase
from gtfs_explorer.infrastructure.importing.normalizers.core import _convert

_FILENAME = "shapes.txt"
_TABLE = "gtfs_shapes"


@dataclass(frozen=True)
class GeometryNormalizationResult:
    """Recuento de puntos de shape normalizados y problemas detectados."""

    row_count: int
    issue_count: int


class GeometryNormalizer:
    """Convierte `shapes.txt` preservando la secuencia y los valores fuente."""

    def normalize(
        self, database: ProjectDatabase, specification: ScheduleSpec
    ) -> GeometryNormalizationResult:
        """Sustituye los shapes y sus problemas de conversión en una transacción."""
        issues: list[tuple[object, ...]] = []
        with database.connection() as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.execute(f"DELETE FROM {_TABLE}")
                connection.execute(
                    "DELETE FROM normalization_issues WHERE file_name = ?", [_FILENAME]
                )
                row_count = 0
                if _FILENAME in _present_files(connection):
                    row_count = self._normalize_file(connection, specification, issues)
                if issues:
                    connection.executemany(
                        "INSERT INTO normalization_issues VALUES (?, ?, ?, ?, ?, ?, ?)", issues
                    )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return GeometryNormalizationResult(row_count, len(issues))

    def _normalize_file(
        self,
        connection: DatabaseConnection,
        specification: ScheduleSpec,
        issues: list[tuple[object, ...]],
    ) -> int:
        fields = specification.files[_FILENAME].fields
        columns = _staging_columns(connection, _FILENAME)
        rows = connection.execute("SELECT * FROM stg_shapes").fetchall()
        for row in rows:
            raw = dict(zip(columns, row, strict=True))
            source_row = int(raw.pop("source_row"))
            source_filename = str(raw.pop("source_filename"))
            raw.pop("extra_columns")
            values = _typed_values(source_row, raw, fields, specification, issues)
            connection.execute(
                "INSERT INTO gtfs_shapes "
                "(source_filename, source_row, raw_values, shape_id, shape_pt_lat, "
                "shape_pt_lon, shape_pt_sequence, shape_dist_traveled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    source_filename,
                    source_row,
                    json.dumps(raw, ensure_ascii=False),
                    values["shape_id"],
                    values["shape_pt_lat"],
                    values["shape_pt_lon"],
                    values["shape_pt_sequence"],
                    values["shape_dist_traveled"],
                ],
            )
        return len(rows)


def _present_files(connection: DatabaseConnection) -> set[str]:
    rows = connection.execute(
        "SELECT original_name FROM stg_source_inventory WHERE known_to_schedule_spec"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _staging_columns(connection: DatabaseConnection, filename: str) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            ["stg_" + filename.removesuffix(".txt")],
        ).fetchall()
    ]


def _typed_values(
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
                        _FILENAME,
                        source_row,
                        field_name,
                        lexeme,
                        "Falta un valor obligatorio.",
                    )
                )
            continue
        try:
            values[field_name] = _convert(lexeme, field, specification)
        except ValueError as error:
            values[field_name] = None
            issues.append(
                (
                    "GTFS_TYPE_CONVERSION_INVALID",
                    "ERROR",
                    _FILENAME,
                    source_row,
                    field_name,
                    lexeme,
                    str(error),
                )
            )
    return values
