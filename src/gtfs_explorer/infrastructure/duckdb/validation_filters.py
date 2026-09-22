"""Predicados parametrizados compartidos para detalles de validación."""

from __future__ import annotations

from gtfs_explorer.domain.validation import ValidationIssueFilter


def validation_filter_clause(
    report_filter: ValidationIssueFilter,
    *,
    issue_alias: str = "i",
    run_alias: str = "r",
) -> tuple[list[str], list[object]]:
    """Devuelve condiciones SQL seguras para cualquier consulta de incidencias.

    El llamador debe unir ``validation_runs`` con ``run_alias``.  Mantener esta
    política en infraestructura evita que la UI y los exportadores se desvíen.
    """
    conditions: list[str] = []
    parameters: list[object] = []
    for column, values in (
        ("severity", report_filter.severities),
        ("category", report_filter.categories),
    ):
        if values is None:
            continue
        if not values:
            conditions.append("FALSE")
            continue
        ordered = sorted(value.value for value in values)
        conditions.append(f"{issue_alias}.{column} IN ({','.join('?' for _ in ordered)})")
        parameters.extend(ordered)
    for column, value in (
        ("file_name", report_filter.file_name),
        ("batch_id", report_filter.batch_id),
        ("rule_code", report_filter.rule_code),
        ("field_name", report_filter.field_name),
        ("entity_type", report_filter.entity_type),
        ("entity_id", report_filter.entity_id),
    ):
        if value is not None:
            conditions.append(f"{issue_alias}.{column} = ?")
            parameters.append(value)
    if report_filter.feed_id is not None:
        conditions.append(f"{run_alias}.feed_id = ?")
        parameters.append(report_filter.feed_id)
    search_text = (report_filter.search_text or "").strip().lower()
    if search_text:
        fields = ("rule_code", "message_key", "field_name", "file_name", "entity_id")
        conditions.append(
            "("
            + " OR ".join(
                f"contains(lower(coalesce({issue_alias}.{field}, '')), ?)" for field in fields
            )
            + ")"
        )
        parameters.extend([search_text] * len(fields))
    return conditions, parameters
