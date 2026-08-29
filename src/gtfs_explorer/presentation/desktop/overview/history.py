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
        type_label.setBuddy(self._type)
        filters.addRow(type_label, self._type)
        status_label = QLabel(t("history.status_label"))
        status_label.setBuddy(self._status)
        filters.addRow(status_label, self._status)
        box = QGroupBox(t("history.title"))
        box_layout = QVBoxLayout(box)
        box_layout.addLayout(filters)
        self._table = QTableWidget(0, 5)
        self._table.setObjectName("operationHistory")
        self._table.setHorizontalHeaderLabels(
            ("Fecha y hora", "Tipo", "Detalle", "Estado", "Duración")
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAccessibleName(t("history.table"))
        box_layout.addWidget(self._table)
        self._empty = QLabel("No hay operaciones registradas todavía.")
        self._empty.setObjectName("operationHistoryEmpty")
        self._empty.setWordWrap(True)
        box_layout.addWidget(self._empty)
        layout.addWidget(box)
        self._type.currentIndexChanged.connect(self.refresh)
        self._status.currentIndexChanged.connect(self.refresh)

    def clear(self) -> None:
        self._table.setRowCount(0)
        self._empty.setText("No hay operaciones registradas todavía.")
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
                    item.setToolTip("Hora local; el ledger conserva UTC")
                self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()
        self._empty.setVisible(not result.items)
        if result.items:
            self._empty.setText(f"Mostrando {len(result.items)} de {result.total} operaciones.")


def _local_timestamp(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")


def _duration_text(operation: Operation, status: OperationDisplayStatus) -> str:
    if status is OperationDisplayStatus.INTERRUPTED or operation.finished_at is None:
        return "Desconocida"
    seconds = max(0, int((operation.finished_at - operation.started_at).total_seconds()))
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d} min {remainder:02d} s"
    return f"{minutes} min {remainder:02d} s"


def _detail_text(operation: Operation) -> str:
    if operation.operation_type is OperationType.IMPORT:
        detail = operation.feed_name or "Feed sin nombre"
        if operation.validation_result is not None:
            detail += f" · {_validation_text(operation.validation_result)}"
            if operation.validation_issue_count is not None:
                detail += f" ({operation.validation_issue_count} incidencias)"
        return detail
    if operation.operation_type is OperationType.EXPORT:
        detail = operation.export_format or "Formato no disponible"
        artifact = operation.artifact_name or "Artefacto no publicado"
        if operation.artifact_size_bytes is not None:
            artifact += f" ({operation.artifact_size_bytes} B)"
        return f"{detail} · {artifact}"
    return "Validación standalone"


def _type_text(value: OperationType) -> str:
    return {
        OperationType.IMPORT: "Importación",
        OperationType.VALIDATION: "Validación",
        OperationType.EXPORT: "Exportación",
    }[value]


def _status_text(value: OperationDisplayStatus) -> str:
    return {
        OperationDisplayStatus.RUNNING: "En curso",
        OperationDisplayStatus.COMPLETED: "Completada",
        OperationDisplayStatus.CANCELLED: "Cancelada",
        OperationDisplayStatus.FAILED: "Fallida",
        OperationDisplayStatus.INTERRUPTED: "Interrumpida",
    }[value]


def _validation_text(value: str) -> str:
    return {"VALID": "Válido", "INVALID": "Inválido", "CANCELLED": "Cancelada"}.get(value, value)
