from __future__ import annotations

from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication

from gtfs_explorer.domain.operations import Operation, OperationStatus, OperationType
from gtfs_explorer.domain.ports import PagedResult, PageRequest
from gtfs_explorer.presentation.desktop.overview.history import OperationHistoryWidget


def _operation(
    operation_type: OperationType,
    status: OperationStatus,
    *,
    started: datetime = datetime(2026, 1, 2, 12),
    finished: datetime | None = datetime(2026, 1, 2, 12, 1, 2),
    **details: object,
) -> Operation:
    return Operation(
        operation_id=f"{operation_type.value.lower()}-{status.value.lower()}",
        project_id="project",
        operation_type=operation_type,
        status=status,
        started_at=started,
        finished_at=finished,
        error_code=None,
        **details,
    )


def _widget(application: QApplication, items: tuple[Operation, ...]) -> OperationHistoryWidget:
    calls: list[tuple[OperationType | None, OperationStatus | None]] = []

    def query(
        operation_type: OperationType | None, status: OperationStatus | None
    ) -> PagedResult[Operation]:
        calls.append((operation_type, status))
        selected = tuple(
            item
            for item in items
            if (operation_type is None or item.operation_type is operation_type)
            and (status is None or item.status is status)
        )
        return PagedResult(selected, len(selected), PageRequest(limit=100))

    widget = OperationHistoryWidget(query)
    widget._query_calls = calls  # type: ignore[attr-defined]
    return widget


def test_empty_state_and_no_legacy_backfill(application: QApplication) -> None:
    widget = _widget(application, ())
    widget.refresh()
    assert widget._table.rowCount() == 0
    assert not widget._empty.isHidden()
    assert "legacy" not in widget._empty.text().casefold()


@pytest.mark.parametrize(
    ("status", "label"),
    (
        (OperationStatus.COMPLETED, "Completada"),
        (OperationStatus.CANCELLED, "Cancelada"),
        (OperationStatus.FAILED, "Fallida"),
    ),
)
def test_import_states_show_feed_validation_and_issue_count(
    application: QApplication, status: OperationStatus, label: str
) -> None:
    operation = _operation(
        OperationType.IMPORT,
        status,
        feed_name="valid-feed.zip",
        validation_result="VALID" if status is OperationStatus.COMPLETED else "INVALID",
        validation_issue_count=0 if status is OperationStatus.COMPLETED else 3,
    )
    widget = _widget(application, (operation,))
    widget.refresh()
    assert widget._table.item(0, 1).text() == "Importación"
    assert widget._table.item(0, 2).text() in {
        "valid-feed.zip · Válido (0 incidencias)",
        "valid-feed.zip · Inválido (3 incidencias)",
    }
    assert widget._table.item(0, 3).text() == label


def test_import_cancelled_and_interrupted_are_distinct(application: QApplication) -> None:
    cancelled = _operation(OperationType.IMPORT, OperationStatus.CANCELLED, finished=None)
    interrupted = _operation(OperationType.IMPORT, OperationStatus.RUNNING, finished=None)
    widget = _widget(application, (cancelled, interrupted))
    widget.refresh()
    assert {widget._table.item(row, 3).text() for row in range(2)} == {"Interrumpida", "Cancelada"}
    assert "Desconocida" in {widget._table.item(row, 4).text() for row in range(2)}


@pytest.mark.parametrize("status", (OperationStatus.COMPLETED, OperationStatus.FAILED))
def test_export_states_show_format_artifact_and_size_without_path(
    application: QApplication, status: OperationStatus
) -> None:
    operation = _operation(
        OperationType.EXPORT,
        status,
        export_format="CSV",
        artifact_name="routes.csv" if status is OperationStatus.COMPLETED else None,
        artifact_size_bytes=128 if status is OperationStatus.COMPLETED else None,
    )
    widget = _widget(application, (operation,))
    widget.refresh()
    assert widget._table.item(0, 2).text() == (
        "CSV · routes.csv (128 B)"
        if status is OperationStatus.COMPLETED
        else "CSV · Artefacto no publicado"
    )
    if status is OperationStatus.COMPLETED:
        assert "routes.csv" in widget._table.item(0, 2).text()


def test_order_duration_timezone_filters_and_refresh(application: QApplication) -> None:
    older = _operation(
        OperationType.IMPORT,
        OperationStatus.COMPLETED,
        started=datetime(2026, 1, 1, 12),
        finished=datetime(2026, 1, 1, 12, 2),
        feed_name="old.zip",
    )
    newer = _operation(
        OperationType.EXPORT,
        OperationStatus.COMPLETED,
        feed_name=None,
        export_format="JSON",
        artifact_name="out.json",
        artifact_size_bytes=8,
    )
    widget = _widget(application, (newer, older))
    widget.refresh()
    assert widget._table.item(0, 2).text() == "JSON · out.json (8 B)"
    assert widget._table.item(1, 4).text() == "2 min 00 s"
    expected = datetime(2026, 1, 2, 12, tzinfo=timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    assert widget._table.item(0, 0).text() == expected
    widget._type.setCurrentIndex(1)
    assert widget._table.rowCount() == 1
    widget.clear()
    assert widget._table.rowCount() == 0


def test_validation_standalone_is_supported(application: QApplication) -> None:
    widget = _widget(
        application, (_operation(OperationType.VALIDATION, OperationStatus.COMPLETED),)
    )
    widget.refresh()
    assert widget._table.item(0, 2).text() == "Validación standalone"


def test_close_reopen_rebuilds_from_query_and_never_displays_absolute_paths(
    application: QApplication,
) -> None:
    operation = _operation(
        OperationType.EXPORT,
        OperationStatus.COMPLETED,
        export_format="CSV",
        artifact_name="report.csv",
        artifact_size_bytes=10,
    )
    widget = _widget(application, (operation,))
    widget.refresh()
    widget.clear()
    widget.refresh()
    visible = " ".join(widget._table.item(0, column).text() for column in range(5))
    assert "C:\\" not in visible
    assert "report.csv" in visible
