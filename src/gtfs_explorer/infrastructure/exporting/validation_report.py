"""Informes de validación incrementales, atómicos y cancelables."""

from __future__ import annotations

import html
import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

from gtfs_explorer.domain.exporting import ExportManifest
from gtfs_explorer.domain.validation import ValidationIssueFilter, ValidationSeverity
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection
from gtfs_explorer.infrastructure.duckdb.validation_filters import validation_filter_clause
from gtfs_explorer.infrastructure.exporting.atomic_output import AtomicOutputWriter

ReportFormat = Literal["json", "html"]
ReportMode = Literal["summary", "full"]
_SCHEMA_VERSION = "1.1.0"
_EXPORT_BATCH_SIZE = 500


ValidationReportFilter = ValidationIssueFilter


class ValidationReportExporter:
    def __init__(self, writer: AtomicOutputWriter | None = None) -> None:
        self._writer = writer or AtomicOutputWriter()

    def estimate(
        self,
        connection: DatabaseConnection,
        *,
        batch_id: str,
        report_filter: ValidationReportFilter | None = None,
    ) -> tuple[int, int]:
        """Devuelve filas seleccionadas y tamaño aproximado, usando una muestra limitada."""
        filter_value = _filter_for_batch(batch_id, report_filter)
        where, params = _where(filter_value)
        total_row = connection.execute(
            "SELECT count(*) FROM validation_issues i JOIN validation_runs r "
            "ON r.batch_id = i.batch_id WHERE " + where,
            params,
        ).fetchone()
        if total_row is None:
            raise ValueError("La consulta de incidencias no devolvió un contador.")
        total = _database_integer(total_row[0])
        sample = connection.execute(
            "SELECT validator, rule_code, severity, category, file_name, row_number, field_name, "
            "entity_type, entity_id, message_key, message_parameters, help_id, occurrence_count "
            "FROM validation_issues i JOIN validation_runs r ON r.batch_id = i.batch_id WHERE "
            + where
            + " ORDER BY i.position LIMIT 32",
            params,
        ).fetchall()
        average = (
            max(256, int(sum(len(json.dumps(_row_payload(row))) for row in sample) / len(sample)))
            if sample
            else 0
        )
        return total, total * average

    def build_payload(
        self,
        connection: DatabaseConnection,
        *,
        batch_id: str,
        report_filter: ValidationReportFilter | None = None,
    ) -> dict[str, object]:
        """Compatibilidad para consumidores pequeños; el flujo de exportación no lo usa."""
        filter_value = _filter_for_batch(batch_id, report_filter)
        header = _header(connection, batch_id, filter_value)
        issues = list(_iter_issue_payloads(connection, filter_value))
        header["issues"] = issues
        return header

    def write(
        self,
        connection: DatabaseConnection,
        destination: Path,
        *,
        batch_id: str,
        report_format: ReportFormat,
        report_filter: ValidationReportFilter | None = None,
        mode: ReportMode = "full",
        overwrite: bool = False,
        is_cancelled: Callable[[], bool] = lambda: False,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> ExportManifest:
        if report_format not in {"json", "html"}:
            raise ValueError("El formato de informe debe ser json o html.")
        filter_value = _filter_for_batch(batch_id, report_filter)
        header = _header(connection, batch_id, filter_value)
        selection = header["selection"]
        assert isinstance(selection, dict)
        selected_count = int(selection["selected_detail_row_count"])
        selected_occurrences = int(selection["selected_occurrence_count"])
        header["export"] = {
            "mode": mode.upper(),
            "exported_detail_row_count": selected_count if mode == "full" else 0,
            "exported_occurrence_count": selected_occurrences if mode == "full" else 0,
            "complete_for_selection": mode == "full",
        }
        if mode == "summary":
            chunks = _summary_chunks(header, report_format)
        else:
            chunks = _full_chunks(connection, filter_value, header, report_format, on_progress)
        run = header["run"]
        assert isinstance(run, dict)
        return self._writer.write(
            destination,
            chunks,
            overwrite=overwrite,
            is_cancelled=is_cancelled,
            manifest_metadata={
                "validation_batch_id": batch_id,
                "report_mode": mode,
                "report_schema_version": _SCHEMA_VERSION,
                "feed_id": str(run["feed_id"]),
                "execution_status": str(run["execution_status"]),
                "validation_outcome": str(run["validation_outcome"] or ""),
                "run_integrity": run["integrity"],
                "export_integrity": header["export"],
                "active_filters": _filter_payload(filter_value),
                "complete_for_selection": mode == "full",
            },
        )


def _filter_for_batch(
    batch_id: str, report_filter: ValidationReportFilter | None
) -> ValidationIssueFilter:
    filter_value = report_filter or ValidationIssueFilter()
    if filter_value.batch_id is not None and filter_value.batch_id != batch_id:
        raise ValueError("El filtro de validación no corresponde al lote solicitado.")
    return replace(filter_value, batch_id=batch_id)


def _header(
    connection: DatabaseConnection, batch_id: str, report_filter: ValidationIssueFilter
) -> dict[str, object]:
    run = connection.execute(
        "SELECT r.feed_id, coalesce(m.execution_status, 'COMPLETED'), m.validation_outcome, "
        "coalesce(m.detected_issue_count, r.total_issue_count), "
        "coalesce(m.persisted_issue_count, 0), coalesce(m.detail_complete, FALSE), "
        "coalesce(m.legacy_truncated, FALSE) FROM validation_runs r "
        "LEFT JOIN validation_run_metadata m "
        "ON m.batch_id = r.batch_id WHERE r.batch_id = ?",
        [batch_id],
    ).fetchone()
    if run is None:
        raise ValueError("No existe el lote de validación solicitado.")
    where, params = _where(report_filter)
    selected_row = connection.execute(
        "SELECT count(*), coalesce(sum(i.occurrence_count), 0) FROM validation_issues i "
        "JOIN validation_runs r ON r.batch_id = i.batch_id WHERE " + where,
        params,
    ).fetchone()
    if selected_row is None:
        raise ValueError("La consulta de incidencias no devolvió un contador.")
    selected = _database_integer(selected_row[0])
    selected_occurrences = _database_integer(selected_row[1])
    totals = _severity_counts(
        connection.execute(
            "SELECT severity, occurrence_count FROM validation_severity_aggregates "
            "WHERE batch_id = ?",
            [batch_id],
        ).fetchall()
    )
    selection_occurrences = _severity_counts(
        connection.execute(
            "SELECT i.severity, sum(i.occurrence_count) FROM validation_issues i "
            "JOIN validation_runs r ON r.batch_id = i.batch_id WHERE "
            + where
            + " GROUP BY i.severity",
            params,
        ).fetchall()
    )
    selection_rows = _severity_counts(
        connection.execute(
            "SELECT i.severity, count(*) FROM validation_issues i "
            "JOIN validation_runs r ON r.batch_id = i.batch_id WHERE "
            + where
            + " GROUP BY i.severity",
            params,
        ).fetchall()
    )
    detected = _database_integer(run[3])
    persisted = _database_integer(run[4])
    return {
        "schema_version": _SCHEMA_VERSION,
        "report_type": "gtfs-explorer.validation",
        "run": {
            "id": batch_id,
            "feed_id": str(run[0]),
            "execution_status": str(run[1]),
            "validation_outcome": None if run[2] is None else str(run[2]),
            "global_total_issue_count": detected,
            "integrity": {
                "detected_issue_count": detected,
                "persisted_issue_count": persisted,
                "detail_complete": bool(run[5]),
                "legacy_truncated": bool(run[6]),
                "omitted_occurrence_count": max(0, detected - persisted),
            },
            "global_severity_occurrence_counts": totals,
        },
        "selection": {
            "active_filters": _filter_payload(report_filter),
            "selected_detail_row_count": selected,
            "selected_occurrence_count": selected_occurrences,
            "severity_occurrence_counts": selection_occurrences,
            "severity_detail_row_counts": selection_rows,
        },
    }


def _full_chunks(
    connection: DatabaseConnection,
    report_filter: ValidationIssueFilter,
    header: dict[str, object],
    report_format: ReportFormat,
    on_progress: Callable[[int, int], None] | None,
) -> Iterator[bytes]:
    selection = header["selection"]
    assert isinstance(selection, dict)
    total = int(selection["selected_detail_row_count"])
    if report_format == "json":
        yield (json.dumps(header, ensure_ascii=False, sort_keys=True)[:-1] + ',"issues":[').encode(
            "utf-8"
        )
        for index, row in enumerate(_iter_issue_payloads(connection, report_filter), 1):
            yield ("," if index > 1 else "").encode() + json.dumps(row, ensure_ascii=False).encode(
                "utf-8"
            )
            if on_progress and (index % _EXPORT_BATCH_SIZE == 0 or index == total):
                on_progress(index, total)
        yield b"]}\n"
    else:
        yield (_html_prefix(header).encode("utf-8"))
        for index, row in enumerate(_iter_issue_payloads(connection, report_filter), 1):
            rule = cast(dict[str, object], row["rule"])
            location = cast(dict[str, object], row["location"])
            message = row["message"]
            yield (
                "<tr><td>{}</td><td>{}</td><td>{}:{} {}</td><td>{}</td></tr>".format(
                    html.escape(str(rule["code"])),
                    html.escape(str(row["severity"])),
                    html.escape(str(location["file"] or "")),
                    location["row"] or "",
                    html.escape(str(location["field"] or "")),
                    html.escape(json.dumps(message, ensure_ascii=False)),
                )
            ).encode("utf-8")
            if on_progress and (index % _EXPORT_BATCH_SIZE == 0 or index == total):
                on_progress(index, total)
        yield b"</tbody></table></body></html>\n"


def _summary_chunks(header: dict[str, object], report_format: ReportFormat) -> Iterator[bytes]:
    if report_format == "json":
        yield (json.dumps(header, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
    else:
        yield (_html_prefix(header) + "</tbody></table></body></html>\n").encode("utf-8")


def _iter_issue_payloads(
    connection: DatabaseConnection, report_filter: ValidationIssueFilter
) -> Iterator[dict[str, object]]:
    where, params = _where(report_filter)
    cursor = connection.execute(
        "SELECT validator, rule_code, severity, category, file_name, row_number, field_name, "
        "entity_type, entity_id, message_key, message_parameters, help_id, occurrence_count "
        "FROM validation_issues i JOIN validation_runs r ON r.batch_id = i.batch_id WHERE "
        + where
        + " ORDER BY i.position",
        params,
    )
    while rows := cursor.fetchmany(_EXPORT_BATCH_SIZE):
        for row in rows:
            yield _row_payload(row)


def _where(report_filter: ValidationIssueFilter) -> tuple[str, list[object]]:
    conditions, params = validation_filter_clause(report_filter)
    return " AND ".join(conditions) if conditions else "TRUE", params


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


def _filter_payload(report_filter: ValidationReportFilter) -> dict[str, object]:
    return {
        "severities": sorted(value.value for value in report_filter.severities)
        if report_filter.severities is not None
        else None,
        "categories": sorted(value.value for value in report_filter.categories)
        if report_filter.categories is not None
        else None,
        "file_name": report_filter.file_name,
        "search_text": report_filter.search_text,
        "rule_code": report_filter.rule_code,
        "field_name": report_filter.field_name,
        "entity_type": report_filter.entity_type,
        "entity_id": report_filter.entity_id,
    }


def _html_prefix(header: dict[str, object]) -> str:
    run = cast(dict[str, object], header["run"])
    integrity = cast(dict[str, object], run["integrity"])
    selection = cast(dict[str, object], header["selection"])
    export = cast(dict[str, object], header["export"])
    context = {
        "batch_id": run["id"],
        "feed_id": run["feed_id"],
        "execution_status": run["execution_status"],
        "validation_outcome": run["validation_outcome"],
        "global_total_issue_count": run["global_total_issue_count"],
        "run_integrity": integrity,
        "global_severity_occurrence_counts": run["global_severity_occurrence_counts"],
        "filters": selection["active_filters"],
        "selection": selection,
    }
    export_rows = "".join(
        "<dt>{}</dt><dd>{}</dd>".format(
            html.escape(label),
            html.escape(str(value)),
        )
        for label, value in (
            ("Report mode", export["mode"]),
            ("Active filters", json.dumps(selection["active_filters"], ensure_ascii=False)),
            ("Selected occurrences", selection["selected_occurrence_count"]),
            ("Exported occurrences", export["exported_occurrence_count"]),
            ("Selected distinct detail rows", selection["selected_detail_row_count"]),
            ("Exported distinct detail rows", export["exported_detail_row_count"]),
            ("Complete for selection", export["complete_for_selection"]),
        )
    )
    warning = ""
    if not integrity["detail_complete"]:
        warning = (
            '<p role="alert"><strong>Advertencia:</strong> esta validación histórica no '
            "conserva todos los detalles detectados originalmente.</p>"
        )
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        "<title>Informe de validación</title></head><body><h1>Informe de validación</h1>"
        + warning
        + "<h2>RUN / VALIDATION INTEGRITY</h2><pre>"
        + html.escape(json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True))
        + "</pre><h2>EXPORT / SELECTION INTEGRITY</h2><dl>"
        + export_rows
        + "</dl><table><thead><tr><th>Regla</th><th>Severidad</th><th>Ubicación</th>"
        "<th>Mensaje</th></tr></thead><tbody>"
    )


def _severity_counts(rows: list[tuple[object, object]]) -> dict[str, int]:
    counts = {severity.value: 0 for severity in ValidationSeverity}
    for severity, count in rows:
        counts[str(severity)] = _database_integer(count)
    return counts


def _database_integer(value: object) -> int:
    if not isinstance(value, int):
        raise ValueError("La base de datos devolvió un contador no entero.")
    return value
