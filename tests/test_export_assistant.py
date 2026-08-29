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
        ExportFormat.MINI_GTFS: "validada localmente",
    }
    for format_, wording in expectations.items():
        widget._format.setCurrentIndex(widget._format.findData(format_.value))
        assert wording in widget._format_help.text().casefold()
        assert widget._bbox.isEnabled() is (format_ is ExportFormat.GEOJSON)
        assert widget._spreadsheet_safe.isEnabled() is (format_ is ExportFormat.CSV)
    assert "rutas" in widget._preview.text()
    widget._format.setCurrentIndex(widget._format.findData(ExportFormat.MINI_GTFS.value))
    assert "no certifica" in widget._format_help.text().casefold()


def test_format_help_describes_current_payload_without_false_table_promises(
    application: QApplication,
) -> None:
    widget = ExportAssistantWidget(executor=lambda request, cancelled: _result())
    widget._routes.setPlainText("R1")
    widget._trips.setPlainText("T1")
    widget._services.setPlainText("S1")

    expectations = {
        ExportFormat.JSON: ("bundle json", "entidades", "dependencias"),
        ExportFormat.CSV: ("route_id", "route_short_name", "route_type"),
        ExportFormat.GEOJSON: ("geojson rfc 7946", "paradas", "shapes"),
        ExportFormat.MINI_GTFS: (
            "subconjunto gtfs autocontenido",
            "dependencias necesarias",
            "validada localmente",
        ),
    }
    for format_, terms in expectations.items():
        widget._format.setCurrentIndex(widget._format.findData(format_.value))
        help_text = widget._format_help.text().casefold()
        assert all(term in help_text for term in terms)
        assert "tabla opcional" not in help_text
        assert "/" not in help_text and "\\" not in help_text


def test_format_help_and_name_follow_the_current_selection(
    application: QApplication,
) -> None:
    widget = ExportAssistantWidget(executor=lambda request, cancelled: _result())
    widget._routes.setPlainText("R1")
    widget._trips.setPlainText("T1")
    widget._services.setPlainText("S1")

    assert "rutas: r1" in widget._format_help.text().casefold()
    assert "viajes: t1" in widget._format_help.text().casefold()
    assert "servicios: s1" in widget._format_help.text().casefold()
    assert "route-r1-trip-t1-service-s1" in widget.request().destination.name.casefold()

    widget._routes.setPlainText("R2")

    help_text = widget._format_help.text().casefold()
    assert "rutas: r2" in help_text
    assert "rutas: r1" not in help_text
    assert "route-r2-trip-t1-service-s1" in widget.request().destination.name.casefold()


def test_help_sanitizes_identifier_context_and_never_shows_a_local_path(
    application: QApplication,
) -> None:
    widget = ExportAssistantWidget(executor=lambda request, cancelled: _result())
    widget._routes.setPlainText(r"C:\secret\R1")

    help_text = widget._format_help.text()

    assert r"C:\secret" not in help_text
    assert "/" not in help_text and "\\" not in help_text


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


def test_export_error_dialog_does_not_show_technical_exception_text(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    messages: list[tuple[object, ...]] = []

    def fail(_request: object, _cancelled: object) -> ExportResult:
        raise RuntimeError(r"C:\Users\José Muñoz\secreto")

    widget = ExportAssistantWidget(executor=fail)
    _configure(widget, tmp_path / "salida.json")
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: messages.append(args))

    widget._execute()

    assert len(messages) == 1
    assert "José Muñoz" not in str(messages[0])
    assert "No se ha podido exportar la salida local." in str(messages[0])
    assert messages[0][-1] is QMessageBox.StandardButton.Ok
    widget.deleteLater()
    application.processEvents()


def test_clear_removes_all_project_export_context(
    application: QApplication, tmp_path: Path
) -> None:
    widget = ExportAssistantWidget(executor=lambda request, cancelled: _result())
    _configure(widget, tmp_path / "project-a.json")
    widget._trips.setPlainText("T1")
    widget._services.setPlainText("weekday")
    widget._destination.setText(str(tmp_path / "project-a.json"))
    widget._bbox.setChecked(True)

    widget.clear()

    request = widget.request()
    assert request.format is ExportFormat.JSON
    assert request.route_ids == frozenset()
    assert request.trip_ids == frozenset()
    assert request.service_ids == frozenset()
    assert request.destination == Path(".")
    assert not widget._bbox.isChecked()
    assert not widget._spreadsheet_safe.isChecked()
