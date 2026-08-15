"""Modelo Qt paginado que nunca materializa el resultado completo."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Literal

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
)

from gtfs_explorer.domain.raw import RawPage, RawQuery, RawRow, RawSort

RawQueryExecutor = Callable[[RawQuery], RawPage]


class PagedTableModel(QAbstractTableModel):
    """Acumula solo páginas ya consultadas y recupera tokens caducados de forma segura."""

    load_failed = Signal(str)

    def __init__(self, execute: RawQueryExecutor, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._execute = execute
        self._request: RawQuery | None = None
        self._page: RawPage | None = None
        self._rows: list[RawRow] = []
        self._next_token: str | None = None
        self._loading = False

    def rowCount(  # noqa: N802 - Qt API
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(  # noqa: N802 - Qt API
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return 0 if parent.isValid() or self._page is None else len(self._page.columns) + 1

    def data(  # noqa: N802 - Qt API
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if not index.isValid() or role not in {
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.ToolTipRole,
        }:
            return None
        row = self._rows[index.row()]
        if index.column() == 0:
            return str(row.source_row)
        value = row.values[index.column() - 1]
        return "" if value is None else value

    def headerData(  # noqa: N802 - Qt API
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation is Qt.Orientation.Horizontal:
            if section == 0:
                return "Fila fuente"
            if self._page is not None and section - 1 < len(self._page.columns):
                return self._page.columns[section - 1].name
        return str(section + 1)

    def canFetchMore(  # noqa: N802 - Qt API
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> bool:
        return not parent.isValid() and self._next_token is not None and not self._loading

    def fetchMore(  # noqa: N802 - Qt API
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> None:
        if parent.isValid() or self._next_token is None or self._request is None or self._loading:
            return
        self._loading = True
        try:
            self._append(self._execute(_with_token(self._request, self._next_token)))
        except ValueError as error:
            self.load_failed.emit(f"La página ya no es válida; se ha recargado la vista. ({error})")
            self.reload()
        except Exception as error:  # la UI debe informar sin dejar un token en bucle
            self.load_failed.emit(str(error) or type(error).__name__)
        finally:
            self._loading = False

    def set_query(self, request: RawQuery) -> None:
        """Sustituye filtros u ordenación y vuelve a cargar solo la primera página."""
        self._request = _with_token(request, None)
        self.reload()

    def reload(self) -> None:
        if self._request is None:
            return
        self.beginResetModel()
        self._page = None
        self._rows = []
        self._next_token = None
        self.endResetModel()
        try:
            self._replace(self._execute(self._request))
        except Exception as error:
            self.load_failed.emit(str(error) or type(error).__name__)

    def clear(self) -> None:
        self._request = None
        self.beginResetModel()
        self._page = None
        self._rows = []
        self._next_token = None
        self.endResetModel()

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        if self._request is None or column <= 0 or self._page is None:
            return
        name = self._page.columns[column - 1].name
        direction: Literal["asc", "desc"] = (
            "asc" if order is Qt.SortOrder.AscendingOrder else "desc"
        )
        self.set_query(
            RawQuery(
                self._request.filename,
                self._request.columns,
                self._request.filters,
                (RawSort(name, direction),),
                self._request.page_size,
            )
        )

    def selected_rows(self, indexes: Iterable[QModelIndex]) -> tuple[tuple[str, ...], ...]:
        """Devuelve una matriz tabulable respetando exactamente las celdas seleccionadas."""
        selected = {(index.row(), index.column()) for index in indexes if index.isValid()}
        if not selected:
            return ()
        row_start = min(row for row, _ in selected)
        row_end = max(row for row, _ in selected)
        column_start = min(column for _, column in selected)
        column_end = max(column for _, column in selected)
        return tuple(
            tuple(
                str(self.data(self.index(row, column)) or "") if (row, column) in selected else ""
                for column in range(column_start, column_end + 1)
            )
            for row in range(row_start, row_end + 1)
        )

    def loaded_rows(self) -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(
                str(self.data(self.index(row, column)) or "")
                for column in range(self.columnCount())
            )
            for row in range(self.rowCount())
        )

    def headers(self) -> tuple[str, ...]:
        return tuple(
            str(self.headerData(column, Qt.Orientation.Horizontal))
            for column in range(self.columnCount())
        )

    def _replace(self, page: RawPage) -> None:
        self.beginResetModel()
        self._page = page
        self._rows = list(page.rows)
        self._next_token = page.next_page_token
        self.endResetModel()

    def _append(self, page: RawPage) -> None:
        if self._page is None or page.columns != self._page.columns:
            raise ValueError("La página raw no coincide con las columnas de la vista.")
        start = len(self._rows)
        end = start + len(page.rows) - 1
        if page.rows:
            self.beginInsertRows(QModelIndex(), start, end)
            self._rows.extend(page.rows)
            self.endInsertRows()
        self._next_token = page.next_page_token


def _with_token(request: RawQuery, token: str | None) -> RawQuery:
    return RawQuery(
        request.filename,
        request.columns,
        request.filters,
        request.sort,
        request.page_size,
        token,
    )
