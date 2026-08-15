"""Comportamiento del modelo Qt de páginas para el inspector raw."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gtfs_explorer.domain.raw import RawColumn, RawPage, RawQuery, RawRow
from gtfs_explorer.presentation.models.paged_table import PagedTableModel


def _page(start: int, count: int, next_token: str | None) -> RawPage:
    return RawPage(
        "stops.txt",
        (RawColumn("stop_id", "ID"), RawColumn("stop_name", "Text")),
        tuple(
            RawRow(index + 2, (f"S{index}", f"Parada {index}"))
            for index in range(start, start + count)
        ),
        next_token,
    )


def test_model_fetches_bounded_pages_and_sorts_without_materializing_large_table(
    application: QApplication,
) -> None:
    requests: list[RawQuery] = []

    def execute(request: RawQuery) -> RawPage:
        requests.append(request)
        return _page(0, 100, "next") if request.page_token is None else _page(100, 100, None)

    model = PagedTableModel(execute)
    model.set_query(RawQuery("stops.txt", ("stop_id", "stop_name"), page_size=100))

    assert model.rowCount() == 100
    assert model.canFetchMore()
    model.fetchMore()
    assert model.rowCount() == 200
    assert not model.canFetchMore()

    model.sort(2, Qt.SortOrder.DescendingOrder)
    assert requests[-1].sort[0].column == "stop_name"
    assert requests[-1].sort[0].direction == "desc"
    assert model.rowCount() == 100


def test_invalid_page_token_recovers_by_reloading_first_page(application: QApplication) -> None:
    calls: list[str | None] = []
    failures: list[str] = []

    def execute(request: RawQuery) -> RawPage:
        calls.append(request.page_token)
        if request.page_token == "expired":
            raise ValueError("token caducado")
        return _page(0, 2, "expired")

    model = PagedTableModel(execute)
    model.load_failed.connect(failures.append)
    model.set_query(RawQuery("stops.txt", ("stop_id", "stop_name")))
    model.fetchMore()

    assert calls == [None, "expired", None]
    assert model.rowCount() == 2
    assert failures and "se ha recargado" in failures[0]


def test_copy_rows_preserves_only_selected_cells(application: QApplication) -> None:
    model = PagedTableModel(lambda _request: _page(0, 2, None))
    model.set_query(RawQuery("stops.txt", ("stop_id", "stop_name")))

    selected = (model.index(0, 1), model.index(1, 2))

    assert model.selected_rows(selected) == (("S0", ""), ("", "Parada 1"))
