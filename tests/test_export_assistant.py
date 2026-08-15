from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from gtfs_explorer.domain.exporting import ExportManifest
from gtfs_explorer.presentation.desktop.exporter.widget import (
    ExportAssistantWidget,
    ExportFormat,
    ExportResult,
)


def _result(*, classification: str = "derivada") -> ExportResult:
    return ExportResult(
        ExportManifest("salida.json", "a" * 64, 12, "salida.json.manifest.json"),
        ("una dependencia opcional se omitió",),
        classification,
    )


def _configure(widget: ExportAssistantWidget, destination: Path) -> None:
    widget._routes.setPlainText("R1")
    widget._destination.setText(str(destination))


def test_formats_explain_classification_and_disable_incompatible_options(
    application: QApplication, tmp_path: Path
) -> None:
    widget = ExportAssistantWidget(executor=lambda request, cancelled: _result())
    _configure(widget, tmp_path / "out")

    expectations = {
        ExportFormat.JSON: "derivada",
        ExportFormat.GEOJSON: "compatible",
        ExportFormat.CSV: "compatible",
        ExportFormat.MINI_GTFS: "oficial",
    }
    for format_, wording in expectations.items():
        widget._format.setCurrentIndex(widget._format.findData(format_.value))
        assert wording in widget._format_help.text().casefold()
        assert widget._bbox.isEnabled() is (format_ is ExportFormat.GEOJSON)
        assert widget._spreadsheet_safe.isEnabled() is (format_ is ExportFormat.CSV)
    assert "rutas" in widget._preview.text()


def test_existing_destination_requires_confirmation_before_executor_runs(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    destination = tmp_path / "exists.json"
    destination.write_text("existing", encoding="utf-8")
    called: list[object] = []
    widget = ExportAssistantWidget(
        executor=lambda request, cancelled: called.append(request) or _result()
    )
    _configure(widget, destination)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: QMessageBox.StandardButton.No,
    )

    widget._execute()

    assert called == []
    assert "ya existe" in widget._preview.text().casefold()


def test_csv_confirmation_targets_the_file_with_its_visible_mode(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    destination = tmp_path / "routes-faithful.csv"
    destination.write_text("existing", encoding="utf-8")
    called: list[object] = []
    widget = ExportAssistantWidget(
        executor=lambda request, cancelled: called.append(request) or _result()
    )
    _configure(widget, tmp_path / "routes.csv")
    widget._format.setCurrentIndex(widget._format.findData(ExportFormat.CSV.value))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)

    widget._execute()

    assert called == []
    assert widget.request().destination == destination
    assert "ya existe" in widget._preview.text().casefold()


def test_executor_receives_cooperative_cancellation(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    observed: list[bool] = []
    widget = ExportAssistantWidget()

    def execute(request: object, cancelled: object) -> ExportResult:
        widget._request_cancel()
        observed.append(cancelled())  # type: ignore[operator]
        return _result()

    widget.set_executor(execute)  # type: ignore[arg-type]
    _configure(widget, tmp_path / "cancelled.geojson")
    widget._format.setCurrentIndex(widget._format.findData(ExportFormat.GEOJSON.value))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    widget._execute()

    assert observed == [True]


def test_result_shows_hash_and_warnings(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    messages: list[str] = []
    widget = ExportAssistantWidget(
        executor=lambda request, cancelled: _result(classification="compatible")
    )
    _configure(widget, tmp_path / "result.geojson")
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda parent, title, message, *buttons: messages.append(message),
    )

    widget._execute()

    assert len(messages) == 1
    assert "SHA-256: " + "a" * 64 in messages[0]
    assert "Aviso: una dependencia opcional se omitió" in messages[0]
