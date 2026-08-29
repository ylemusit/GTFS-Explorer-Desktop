"""Sizing acotado de la tabla RAW sobre la página materializada."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QHeaderView

import gtfs_explorer.presentation.desktop.raw.widget as raw_widget
from gtfs_explorer.domain.raw import RawColumn, RawPage, RawQuery, RawRow
from gtfs_explorer.presentation.desktop.raw.widget import (
    RAW_SIZING_MAX_WIDTH,
    RAW_SIZING_MIN_WIDTH,
    RAW_SIZING_SAMPLE_ROWS,
    RawInspectorWidget,
)


def _widget(application: QApplication, rows: tuple[RawRow, ...]) -> RawInspectorWidget:
    def execute(query: RawQuery) -> RawPage:
        return RawPage(
            query.filename,
            tuple(RawColumn(name, "Text") for name in query.columns),
            rows,
            None,
        )

    widget = RawInspectorWidget(execute)
    widget.configure({"routes.txt": ("id", "description"), "stops.txt": ("id",)})
    return widget


def test_raw_sizing_covers_headers_content_and_bounds_long_values(
    application: QApplication,
) -> None:
    widget = _widget(
        application,
        (
            RawRow(1, ("R1", "Descripción mediana")),
            RawRow(2, ("R2", "x" * 2000)),
        ),
    )

    id_width = widget._table.columnWidth(1)
    description_width = widget._table.columnWidth(2)

    assert RAW_SIZING_MIN_WIDTH <= id_width <= RAW_SIZING_MAX_WIDTH
    assert RAW_SIZING_MIN_WIDTH <= description_width <= RAW_SIZING_MAX_WIDTH
    assert description_width > id_width


def test_raw_sizing_handles_empty_table_and_long_header(
    application: QApplication,
) -> None:
    def execute(query: RawQuery) -> RawPage:
        return RawPage(
            query.filename,
            (RawColumn("header_" + "x" * 500, "Text"),),
            (),
            None,
        )

    widget = RawInspectorWidget(execute)
    widget.configure({"empty.txt": ("field",)})

    assert widget._model.rowCount() == 0
    assert widget._table.columnWidth(1) == RAW_SIZING_MAX_WIDTH


def test_raw_sizing_is_sampled_and_does_not_depend_on_total_rows(
    application: QApplication,
) -> None:
    rows = tuple(RawRow(index, ("ok", "x")) for index in range(1, RAW_SIZING_SAMPLE_ROWS + 1)) + (
        RawRow(9999, ("ok", "z" * 1000)),
    )
    widget = _widget(application, rows)

    assert widget._table.columnWidth(2) < RAW_SIZING_MAX_WIDTH


def test_raw_sizing_changes_with_table_and_keeps_manual_resize_available(
    application: QApplication,
) -> None:
    widget = _widget(application, (RawRow(1, ("A", "short")),))
    widget._files.setCurrentText("stops.txt")

    assert widget._model.headers() == ("Fila fuente", "id")
    assert widget._model.columnCount() == 2
    assert (
        widget._table.horizontalHeader().sectionResizeMode(1) == QHeaderView.ResizeMode.Interactive
    )
    widget._table.setColumnWidth(1, 211)
    assert widget._table.columnWidth(1) == 211


def test_raw_export_excludes_source_metadata_column(
    application: QApplication, tmp_path, monkeypatch
) -> None:
    widget = _widget(application, (RawRow(125, ("R1", "short")),))
    destination = tmp_path / "raw.csv"
    monkeypatch.setattr(
        raw_widget.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(destination), "CSV (*.csv)"),
    )

    widget._export_loaded()

    assert destination.with_name("raw-faithful.csv").read_text(encoding="utf-8") == (
        "id,description\nR1,short\n"
    )
