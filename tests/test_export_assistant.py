from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from gtfs_explorer.domain.exporting import ExportManifest
from gtfs_explorer.presentation.desktop.exporter.widget import (
    ExportAssistantWidget,
    ExportFormat,
    ExportResult,
    ExportRouteOption,
    ExportServiceOption,
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


def test_multiple_routes_and_services_are_one_explicit_export_pack(
    application: QApplication, tmp_path: Path
) -> None:
    widget = ExportAssistantWidget(executor=lambda request, cancelled: _result())
    widget._routes.setPlainText("R1\nR2")
    widget._services.setPlainText("weekday\nweekend")
    widget._destination.setText(str(tmp_path / "pack.json"))

    request = widget.request()

    assert request.is_pack
    assert "export pack" in widget._format_help.text().casefold()
    assert "route-r1-r2" in widget._format_help.text().casefold()


def test_inventory_selects_routes_filters_services_and_sends_selected_ids(
    application: QApplication, tmp_path: Path
) -> None:
    captured: list[object] = []
    widget = ExportAssistantWidget(
        executor=lambda request, cancelled: captured.append(request) or _result()
    )
    widget.set_inventory(
        (
            ExportRouteOption("R1", "201 — Centro (R1)"),
            ExportRouteOption("R2", "205 — Puerto (R2)"),
        ),
        (
            ExportServiceOption("weekday", "weekday · LMJV", frozenset({"R1"})),
            ExportServiceOption("weekend", "weekend · SD", frozenset({"R2"})),
        ),
    )
    widget._route_search.setText("puerto")
    assert widget._route_inventory.count() == 1
    widget._route_inventory.item(0).setCheckState(Qt.CheckState.Checked)
    assert widget._service_inventory.count() == 1
    widget._service_inventory.item(0).setCheckState(Qt.CheckState.Checked)
    widget._destination.setText(str(tmp_path / "selected.json"))

    request = widget.request()

    assert request.route_ids == frozenset({"R2"})
    assert request.service_ids == frozenset({"weekend"})
    assert "1 rutas" in widget._preview.text()


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
    monkeypatch.setattr(widget, "_show_export_completed", lambda *args: None)
    widget._execute()

    assert observed == [True]


def test_result_shows_hash_and_warnings(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    dialogs: list[QMessageBox] = []
    widget = ExportAssistantWidget(
        executor=lambda request, cancelled: _result(classification="compatible")
    )
    _configure(widget, tmp_path / "result.geojson")
    widget._format.setCurrentIndex(widget._format.findData(ExportFormat.GEOJSON.value))
    monkeypatch.setattr(
        QMessageBox, "exec", lambda dialog: dialogs.append(dialog) or QMessageBox.StandardButton.Ok
    )

    widget._execute()

    assert len(dialogs) == 1
    message = dialogs[0].text()
    assert "Nombre del archivo: salida.json" in message
    assert f"Ruta completa de destino: {str((tmp_path / 'result.geojson').resolve())}" in message
    assert "SHA-256: " + "a" * 64 in message
    assert "Aviso: una dependencia opcional se omitió" in message


def _click_completion_action(application: QApplication, label: str) -> None:
    def click() -> None:
        for window in application.topLevelWidgets():
            if isinstance(window, QMessageBox) and window.isVisible():
                for button in window.buttons():
                    if button.text() == label:
                        button.click()
                        return
        QTimer.singleShot(10, click)

    QTimer.singleShot(0, click)


def test_completion_dialog_shows_destination_and_opens_its_folder(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    destination = tmp_path / "exports" / "mini.zip"
    destination.parent.mkdir()
    destination.write_bytes(b"zip")
    opened: list[object] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    widget = ExportAssistantWidget()
    _click_completion_action(application, "Abrir carpeta")
    QTimer.singleShot(20, lambda: _click_completion_action(application, "Aceptar"))

    widget._show_export_completed(destination, _result(classification="Mini-GTFS"), "Sin avisos.")

    assert len(opened) == 1
    assert Path(opened[0].toLocalFile()) == destination.parent.resolve()  # type: ignore[union-attr]


def test_completion_dialog_copy_path_action_copies_full_destination(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    copied: list[str] = []

    class Clipboard:
        def setText(self, value: str) -> None:  # noqa: N802 - API Qt
            copied.append(value)

    destination = tmp_path / "exports" / "mini.zip"
    destination.parent.mkdir()
    destination.write_bytes(b"zip")
    monkeypatch.setattr(QApplication, "clipboard", lambda: Clipboard())
    widget = ExportAssistantWidget()
    _click_completion_action(application, "Copiar ruta")
    QTimer.singleShot(20, lambda: _click_completion_action(application, "Aceptar"))

    widget._show_export_completed(destination, _result(classification="Mini-GTFS"), "Sin avisos.")

    assert copied == [str(destination.resolve())]


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
