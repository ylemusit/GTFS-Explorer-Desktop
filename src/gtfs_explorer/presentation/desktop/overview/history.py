"""Historial visible de operaciones del proyecto."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.domain.operations import (
    Operation,
    OperationDisplayStatus,
    OperationStatus,
    OperationType,
    display_status,
)
from gtfs_explorer.domain.ports import PagedResult
from gtfs_explorer.presentation.desktop.i18n import t

OperationQuery = Callable[[OperationType | None, OperationStatus | None], PagedResult[Operation]]


class OperationHistoryWidget(QWidget):
    """Tabla compacta y segura: solo muestra datos derivados del ledger."""

    def __init__(self, query: OperationQuery, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._query = query
        layout = QVBoxLayout(self)
        filters = QFormLayout()
        self._type = QComboBox()
        self._type.setObjectName("operationHistoryTypeFilter")
        self._type.setAccessibleName(t("history.type"))
        self._type.addItem(t("history.all_operations"), None)
        self._type.addItem(t("history.imports"), OperationType.IMPORT)
        self._type.addItem(t("history.validations"), OperationType.VALIDATION)
        self._type.addItem(t("history.exports"), OperationType.EXPORT)
        self._status = QComboBox()
        self._status.setObjectName("operationHistoryStatusFilter")
        self._status.setAccessibleName(t("history.status"))
        self._status.addItem(t("history.all_statuses"), None)
        for status in OperationStatus:
            self._status.addItem(_status_text(OperationDisplayStatus(status)), status)
        type_label = QLabel(t("history.type_label"))
        self._type_label = type_label
        type_label.setBuddy(self._type)
        filters.addRow(type_label, self._type)
        status_label = QLabel(t("history.status_label"))
        self._status_label = status_label
        status_label.setBuddy(self._status)
        filters.addRow(status_label, self._status)
        box = QGroupBox(t("history.title"))
        self._box = box
        box_layout = QVBoxLayout(box)
        box_layout.addLayout(filters)
        self._table = QTableWidget(0, 5)
        self._table.setObjectName("operationHistory")
        self._table.setHorizontalHeaderLabels(
            (
                t("history.date_header"),
                t("history.type_header"),
                t("history.detail_header"),
                t("history.status_header"),
                t("history.duration_header"),
            )
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAccessibleName(t("history.table"))
        box_layout.addWidget(self._table)
        self._empty = QLabel(t("history.empty"))
        self._empty.setObjectName("operationHistoryEmpty")
        self._empty.setWordWrap(True)
        box_layout.addWidget(self._empty)
        layout.addWidget(box)
        self._type.currentIndexChanged.connect(self.refresh)
        self._status.currentIndexChanged.connect(self.refresh)

    def clear(self) -> None:
        self._table.setRowCount(0)
        self._empty.setText(t("history.empty"))
        self._empty.show()

    def refresh(self) -> None:
        type_value = self._type.currentData()
        status_value = self._status.currentData()
        operation_type = OperationType(type_value) if type_value is not None else None
        status = OperationStatus(status_value) if status_value is not None else None
        result = self._query(operation_type, status)
        self._table.setRowCount(len(result.items))
        for row, operation in enumerate(result.items):
            values = (
                _local_timestamp(operation.started_at),
                _type_text(operation.operation_type),
                _detail_text(operation),
                _status_text(display_status(operation, frozenset())),
                _duration_text(operation, display_status(operation, frozenset())),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setToolTip(t("history.local_time_tooltip"))
                self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()
        self._empty.setVisible(not result.items)
        if result.items:
            self._empty.setText(t("history.showing", count=len(result.items), total=result.total))

    def retranslate_ui(self) -> None:
        """Actualiza filtros, cabeceras y valores derivados del ledger."""
        selected_type = self._type.currentData()
        selected_status = self._status.currentData()
        self._box.setTitle(t("history.title"))
        self._type_label.setText(t("history.type_label"))
        self._status_label.setText(t("history.status_label"))
        self._type.blockSignals(True)
        self._type.clear()
        self._type.addItem(t("history.all_operations"), None)
        self._type.addItem(t("history.imports"), OperationType.IMPORT)
        self._type.addItem(t("history.validations"), OperationType.VALIDATION)
        self._type.addItem(t("history.exports"), OperationType.EXPORT)
        self._type.setCurrentIndex(max(0, self._type.findData(selected_type)))
        self._type.blockSignals(False)
        self._status.blockSignals(True)
        self._status.clear()
        self._status.addItem(t("history.all_statuses"), None)
        for status in OperationStatus:
            self._status.addItem(_status_text(OperationDisplayStatus(status)), status)
        self._status.setCurrentIndex(max(0, self._status.findData(selected_status)))
        self._status.blockSignals(False)
        self._table.setHorizontalHeaderLabels(
            (
                t("history.date_header"),
                t("history.type_header"),
                t("history.detail_header"),
                t("history.status_header"),
                t("history.duration_header"),
            )
        )
        self._table.setAccessibleName(t("history.table"))
        self._empty.setText(t("history.empty"))
        self.refresh()


def _local_timestamp(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")


def _duration_text(operation: Operation, status: OperationDisplayStatus) -> str:
    if status is OperationDisplayStatus.INTERRUPTED or operation.finished_at is None:
        return t("history.duration_unknown")
    seconds = max(0, int((operation.finished_at - operation.started_at).total_seconds()))
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d} min {remainder:02d} s"
    return f"{minutes} min {remainder:02d} s"


def _detail_text(operation: Operation) -> str:
    if operation.operation_type is OperationType.IMPORT:
        detail = operation.feed_name or t("history.feed_unknown")
        if operation.validation_result is not None:
            detail += f" · {_validation_text(operation.validation_result)}"
            if operation.validation_issue_count is not None:
                detail += f" ({operation.validation_issue_count} {t('history.issues')})"
        return detail
    if operation.operation_type is OperationType.EXPORT:
        detail = operation.export_format or t("history.format_unavailable")
        artifact = operation.artifact_name or t("history.artifact_unpublished")
        if operation.artifact_size_bytes is not None:
            artifact += f" ({operation.artifact_size_bytes} B)"
        return f"{detail} · {artifact}"
    return t("history.standalone_validation")


def _type_text(value: OperationType) -> str:
    return {
        OperationType.IMPORT: t("history.import"),
        OperationType.VALIDATION: t("history.validations"),
        OperationType.EXPORT: t("history.exports"),
    }[value]


def _status_text(value: OperationDisplayStatus) -> str:
    return {
        OperationDisplayStatus.RUNNING: t("history.status_running"),
        OperationDisplayStatus.COMPLETED: t("history.status_completed"),
        OperationDisplayStatus.CANCELLED: t("history.status_cancelled"),
        OperationDisplayStatus.FAILED: t("history.status_failed"),
        OperationDisplayStatus.INTERRUPTED: t("history.status_interrupted"),
    }[value]


def _validation_text(value: str) -> str:
    return {
        "VALID": t("history.validation_valid"),
        "INVALID": t("history.validation_invalid"),
        "CANCELLED": t("history.status_cancelled"),
    }.get(value, value)
