"""Flujos de la vista Qt de validación."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gtfs_explorer.domain.ports import PagedResult, PageRequest
from gtfs_explorer.domain.validation import (
    ValidationCategory,
    ValidationEntity,
    ValidationIssueFilter,
    ValidationIssueSummary,
    ValidationSeverity,
)
from gtfs_explorer.presentation.desktop.validation.widget import ValidationWidget


def _issue(origin: str = "gtfs-explorer") -> ValidationIssueSummary:
    return ValidationIssueSummary(
        "batch-1",
        1,
        "RULE_X",
        origin,
        ValidationSeverity.ERROR,
        ValidationCategory.FIELD,
        "stops.txt",
        4,
        "stop_id",
        ValidationEntity("stop", "S<script>"),
        "validation.<script>",
        {"value": "<script>"},
        "validation/RULE_X",
        1,
    )


def test_validation_widget_filters_safely_and_exposes_origin_actions(
    application: QApplication,
) -> None:
    navigated: list[tuple[str, str | None, str | None]] = []
    help_ids: list[str] = []
    exported: list[tuple[str, ValidationIssueFilter]] = []

    def execute(
        report_filter: ValidationIssueFilter, page: PageRequest
    ) -> PagedResult[ValidationIssueSummary]:
        assert page.limit == 100
        return PagedResult((_issue("mobilitydata"),), 1, page)

    widget = ValidationWidget(
        execute,
        navigate_to_raw=lambda *args: navigated.append(args),
        show_help=help_ids.append,
        export_report=lambda *args: exported.append(args),
    )
    widget.refresh()
    widget._table.selectRow(0)

    origin = widget._table.item(0, 2)
    assert origin is not None and origin.text() == "MobilityData"
    assert "<script>" in widget._detail.toPlainText()
    widget._go_to_raw.click()
    widget._help.click()
    widget._export.click()

    assert navigated == [("stops.txt", "stop_id", "S<script>")]
    assert help_ids == ["validation/RULE_X"]
    assert exported and exported[0][0] == "batch-1"
    widget.deleteLater()
    application.processEvents()
