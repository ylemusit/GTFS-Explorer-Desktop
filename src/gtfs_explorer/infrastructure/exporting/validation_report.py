"""Informes de validación JSON y HTML locales, deterministas y seguros."""

from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from gtfs_explorer.domain.exporting import ExportManifest
from gtfs_explorer.domain.validation import ValidationCategory, ValidationSeverity
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection
from gtfs_explorer.infrastructure.exporting.atomic_output import AtomicOutputWriter

ReportFormat = Literal["json", "html"]
_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class ValidationReportFilter:
    """Filtro explícito: no contiene SQL ni acepta fragmentos arbitrarios."""

    severities: frozenset[ValidationSeverity] | None = None
    categories: frozenset[ValidationCategory] | None = None


class ValidationReportExporter:
    """Lee problemas persistidos y publica un informe atómico con su manifiesto."""

    def __init__(self, writer: AtomicOutputWriter | None = None) -> None:
        self._writer = writer or AtomicOutputWriter()

    def build_payload(
        self,
        connection: DatabaseConnection,
        *,
        batch_id: str,
        report_filter: ValidationReportFilter | None = None,
    ) -> dict[str, object]:
        filter_value = report_filter or ValidationReportFilter()
        rows = _issue_rows(connection, batch_id, filter_value)
        summary = Counter(str(row["severity"]) for row in rows)
        run = connection.execute(
            "SELECT feed_id, status, total_issue_count, stored_issue_count, omitted_issue_count "
            "FROM validation_runs WHERE batch_id = ?",
            [batch_id],
        ).fetchone()
        if run is None:
            raise ValueError("No existe el lote de validación solicitado.")
        return {
            "schema_version": _SCHEMA_VERSION,
            "report_type": "gtfs-explorer.validation",
            "batch": {
                "id": batch_id,
                "feed_id": str(run[0]),
                "state": str(run[1]),
                "total_issue_count": int(run[2]),
                "stored_issue_count": int(run[3]),
                "omitted_issue_count": int(run[4]),
            },
            "filter": _filter_payload(filter_value),
            "summary_by_severity": {
                severity.value: summary.get(severity.value, 0) for severity in ValidationSeverity
            },
            "issues": rows,
        }

    def write(
        self,
        connection: DatabaseConnection,
        destination: Path,
        *,
        batch_id: str,
        report_format: ReportFormat,
        report_filter: ValidationReportFilter | None = None,
        overwrite: bool = False,
    ) -> ExportManifest:
        payload = self.build_payload(connection, batch_id=batch_id, report_filter=report_filter)
        if report_format == "json":
            contents = (
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            ).encode("utf-8")
        elif report_format == "html":
            contents = _html_document(payload).encode("utf-8")
        else:
            raise ValueError("El formato de informe debe ser json o html.")
        return self._writer.write(destination, (contents,), overwrite=overwrite)


def _issue_rows(
    connection: DatabaseConnection, batch_id: str, report_filter: ValidationReportFilter
) -> list[dict[str, object]]:
    conditions = ["batch_id = ?"]
    parameters: list[object] = [batch_id]
    _append_in_condition("severity", report_filter.severities, conditions, parameters)
    _append_in_condition("category", report_filter.categories, conditions, parameters)
    query = (
        "SELECT validator, rule_code, severity, category, file_name, row_number, field_name, "
        "entity_type, entity_id, message_key, message_parameters, help_id, occurrence_count "
        "FROM validation_issues WHERE " + " AND ".join(conditions) + " ORDER BY position"
    )
    return [_row_payload(row) for row in connection.execute(query, parameters).fetchall()]


def _append_in_condition(
    column: str,
    values: frozenset[ValidationSeverity] | frozenset[ValidationCategory] | None,
    conditions: list[str],
    parameters: list[object],
) -> None:
    if values is None:
        return
    if not values:
        conditions.append("FALSE")
        return
    ordered_values = sorted(value.value for value in values)
    conditions.append(f"{column} IN ({','.join('?' for _ in ordered_values)})")
    parameters.extend(ordered_values)


def _row_payload(row: tuple[object, ...]) -> dict[str, object]:
    return {
        "rule": {"code": str(row[1]), "origin": str(row[0])},
        "severity": str(row[2]),
        "category": str(row[3]),
        "location": {
            "file": row[4],
            "row": _database_integer(row[5]) if row[5] is not None else None,
            "field": row[6],
            "entity_type": row[7],
            "entity_id": row[8],
        },
        "message": {"key": str(row[9]), "parameters": json.loads(str(row[10]))},
        "help_id": str(row[11]),
        "occurrence_count": _database_integer(row[12]),
    }


def _filter_payload(report_filter: ValidationReportFilter) -> dict[str, list[str] | None]:
    return {
        "severities": (
            sorted(severity.value for severity in report_filter.severities)
            if report_filter.severities is not None
            else None
        ),
        "categories": (
            sorted(category.value for category in report_filter.categories)
            if report_filter.categories is not None
            else None
        ),
    }


def _database_integer(value: object) -> int:
    if not isinstance(value, int):
        raise ValueError("La base de datos devolvió un contador no entero.")
    return value


def _html_document(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        '<!doctype html>\n<html lang="es"><head><meta charset="utf-8">'
        "<title>Informe de validación GTFS Explorer</title></head><body>"
        "<h1>Informe de validación GTFS Explorer</h1><pre>"
        + html.escape(serialized, quote=True)
        + "</pre></body></html>\n"
    )
