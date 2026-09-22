"""Flujos de la vista Qt de validación."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gtfs_explorer.domain.overview import ValidationOverview
from gtfs_explorer.domain.ports import PagedResult, PageRequest
from gtfs_explorer.domain.validation import (
    ValidationCategory,
    ValidationEntity,
    ValidationIssueFilter,
    ValidationIssueSummary,
    ValidationRuleSummary,
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


def test_validation_clear_restores_default_filters_and_selection(application: QApplication) -> None:
    widget = ValidationWidget(lambda _filter, _page: PagedResult((), 0, PageRequest()))
    widget._severity.setCurrentIndex(1)
    widget._category.setCurrentIndex(1)
    widget._table.setRowCount(1)
    widget._table.setCurrentCell(0, 0)
    widget._detail.setPlainText("detalle del proyecto A")

    widget.clear()

    assert widget._severity.currentIndex() == 0
    assert widget._category.currentIndex() == 0
    assert widget._table.rowCount() == 0
    assert widget._table.currentRow() == -1
    assert widget._detail.toPlainText() == ""
    widget.deleteLater()
    application.processEvents()


def test_validation_widget_presents_location_message_and_run_summary(
    application: QApplication,
) -> None:
    issue = ValidationIssueSummary(
        "batch-1",
        1,
        "GTFS_STOP_ID_REQUIRED",
        "gtfs-explorer",
        ValidationSeverity.ERROR,
        ValidationCategory.FIELD,
        "stops.txt",
        125,
        "stop_id",
        ValidationEntity("stop", "S125"),
        "validation.required_value_missing",
        {"value": "<script>"},
        "validation/GTFS_STOP_ID_REQUIRED",
        1,
    )

    widget = ValidationWidget(
        lambda _filter, page: PagedResult((issue,), 3, page),
        list_files=lambda: ("routes.txt", "stops.txt"),
        query_summary=lambda: ValidationOverview(1, 3, ("VALID",)),
    )
    widget.refresh()

    assert widget._table.columnCount() == 9
    rule = widget._table.item(0, 3)
    file_name = widget._table.item(0, 4)
    source_row = widget._table.item(0, 5)
    field = widget._table.item(0, 6)
    message = widget._table.item(0, 8)
    assert rule is not None and rule.text() == "GTFS_STOP_ID_REQUIRED"
    assert file_name is not None and file_name.text() == "stops.txt"
    assert source_row is not None and source_row.text() == "125"
    assert field is not None and field.text() == "stop_id"
    assert message is not None and message.toolTip() == "validation.required_value_missing"
    assert "VALID" in widget._summary.text()
    assert "3 incidencias registradas" in widget._summary.text()

    widget._table.selectRow(0)
    assert widget.selected_issue is issue
    assert "Fila fuente: 125" in widget._detail.toPlainText()
    assert "Campo: stop_id" in widget._detail.toPlainText()
    assert "<script>" in widget._detail.toPlainText()
    widget.deleteLater()
    application.processEvents()


def test_validation_widget_filters_file_and_text_case_insensitively(
    application: QApplication,
) -> None:
    calls: list[ValidationIssueFilter] = []

    def execute(
        report_filter: ValidationIssueFilter, page: PageRequest
    ) -> PagedResult[ValidationIssueSummary]:
        calls.append(report_filter)
        return PagedResult((), 0, page)

    widget = ValidationWidget(execute, list_files=lambda: ("routes.txt", "stops.txt"))
    widget.refresh()
    widget._file_filter.setCurrentIndex(widget._file_filter.findData("stops.txt"))
    widget._search.setText("StOp_Id")
    widget._severity.setCurrentIndex(widget._severity.findData(ValidationSeverity.ERROR))
    widget._category.setCurrentIndex(widget._category.findData(ValidationCategory.FIELD))
    widget.refresh()

    assert calls
    assert calls[-1].file_name == "stops.txt"
    assert calls[-1].search_text == "StOp_Id"
    assert calls[-1].severities == frozenset({ValidationSeverity.ERROR})
    assert calls[-1].categories == frozenset({ValidationCategory.FIELD})
    widget.deleteLater()
    application.processEvents()


def test_validation_widget_sorting_keeps_source_row_and_selected_dto(
    application: QApplication,
) -> None:
    first = _issue()
    second = ValidationIssueSummary(
        "batch-1",
        2,
        "RULE_Y",
        "gtfs-explorer",
        ValidationSeverity.WARNING,
        ValidationCategory.FIELD,
        "stops.txt",
        125,
        "stop_name",
        ValidationEntity("stop", "S125"),
        "validation.other",
        {},
        "validation/RULE_Y",
        1,
    )
    navigated: list[tuple[str, str | None, str | None]] = []
    widget = ValidationWidget(
        lambda _filter, page: PagedResult((first, second), 2, page),
        navigate_to_raw=lambda *args: navigated.append(args),
    )
    widget.refresh()
    widget._table.sortItems(5, Qt.SortOrder.DescendingOrder)
    widget._table.selectRow(0)
    widget._go_to_raw.click()

    source_row = widget._table.item(0, 5)
    assert source_row is not None and source_row.text() == "125"
    assert widget.selected_issue is second
    assert navigated == [("stops.txt", "stop_name", "S125")]
    widget.deleteLater()
    application.processEvents()


def test_validation_widget_does_not_materialize_large_result_and_hides_private_context(
    application: QApplication,
) -> None:
    issue = ValidationIssueSummary(
        "batch-1",
        1,
        "RULE_PRIVATE",
        "internal",
        ValidationSeverity.NOTICE,
        ValidationCategory.BEST_PRACTICE,
        None,
        None,
        None,
        None,
        "validation.notice",
        {
            "value": "ok",
            "path": r"C:\Users\yeison\private\feed.zip",
            "traceback": "secret traceback",
        },
        "validation/RULE_PRIVATE",
        100000,
    )
    requests: list[PageRequest] = []

    def execute(
        _filter: ValidationIssueFilter, page: PageRequest
    ) -> PagedResult[ValidationIssueSummary]:
        requests.append(page)
        return PagedResult((issue,), 100000, page)

    widget = ValidationWidget(execute)
    widget.refresh()
    widget._table.selectRow(0)

    detail = widget._detail.toPlainText()
    assert requests[-1].limit == 100
    assert widget._table.rowCount() == 1
    file_name = widget._table.item(0, 4)
    source_row = widget._table.item(0, 5)
    assert file_name is not None and file_name.text() == "Alcance global"
    assert source_row is not None and source_row.text() == "Sin fila física"
    assert "secret traceback" not in detail
    assert "C:\\Users\\yeison" not in detail
    assert "value=ok" in detail
    widget.clear()
    assert widget._file_filter.currentIndex() == 0
    assert widget._search.text() == ""
    widget.deleteLater()
    application.processEvents()


def test_validation_widget_displays_rule_aggregate_counts_without_conflating_them(
    application: QApplication,
) -> None:
    rule = ValidationRuleSummary(
        "GTFS_SHARED_STOP",
        "gtfs-explorer",
        ValidationSeverity.WARNING,
        ValidationCategory.REFERENCE,
        occurrence_count=7,
        affected_entity_count=2,
    )
    widget = ValidationWidget(
        lambda _filter, page: PagedResult((_issue(),), 1, page),
        query_rule_summaries=lambda _filter: (rule,),
    )

    widget.refresh()

    assert widget._rule_summary.text() == (
        "GTFS_SHARED_STOP — WARNING · REFERENCE: 7 incidencias · 2 entidades"
    )
    widget.deleteLater()
    application.processEvents()
