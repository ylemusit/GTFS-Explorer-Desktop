from __future__ import annotations

from pathlib import Path
from threading import Event
from time import monotonic

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


def _wait_until(application: QApplication, predicate: object, timeout: float = 2.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        application.processEvents()
        if predicate():  # type: ignore[operator]
            return
    assert predicate()  # type: ignore[operator]


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


def test_switching_formats_does_not_leak_geospatial_state(
    application: QApplication, tmp_path: Path
) -> None:
    widget = ExportAssistantWidget(executor=lambda request, cancelled: _result())
    _configure(widget, tmp_path / "out.kmz")
    widget._format.setCurrentIndex(widget._format.findData(ExportFormat.KMZ.value))
    widget._profile.setCurrentIndex(2)
    widget._version.setText("should-not-leak")

    widget._format.setCurrentIndex(widget._format.findData(ExportFormat.COMPLETE_GTFS.value))
    request = widget.request()

    assert request.format is ExportFormat.COMPLETE_GTFS
    assert request.kml_profile is None
    assert request.version_id is None
    assert not widget._profile.isEnabled()
    assert not widget._version.isEnabled()


def test_auto_generated_destination_tracks_each_format_switch(
    application: QApplication,
) -> None:
    widget = ExportAssistantWidget(executor=lambda request, cancelled: _result())
    widget._routes.setPlainText("R1")

    for format_, suffix in (
        (ExportFormat.KMZ, ".kmz"),
        (ExportFormat.KML, ".kml"),
        (ExportFormat.CSV, ".csv"),
        (ExportFormat.COMPLETE_GTFS, ".zip"),
        (ExportFormat.JSON, ".json"),
    ):
        widget._format.setCurrentIndex(widget._format.findData(format_.value))
        assert widget._destination.text().endswith(suffix)
        assert widget.request().destination.suffix == suffix


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


def test_executor_receives_cooperative_cancellation_from_qt_event_loop(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    observed: list[bool] = []
    entered_work = Event()
    widget = ExportAssistantWidget()

    def execute(request: object, cancelled: object) -> ExportResult:
        entered_work.set()
        while not cancelled():  # type: ignore[operator]
            pass
        observed.append(True)
        return _result()

    widget.set_executor(execute)  # type: ignore[arg-type]
    _configure(widget, tmp_path / "cancelled.geojson")
    widget._format.setCurrentIndex(widget._format.findData(ExportFormat.GEOJSON.value))
    monkeypatch.setattr(widget, "_show_export_completed", lambda *args: None)
    widget._execute()
    _wait_until(application, entered_work.is_set)
    widget._request_cancel()
    _wait_until(application, lambda: widget._active_export_generation is None)

    assert observed == [True]
    assert widget._export_jobs == {}
    assert widget._cancel_token is None


def test_repeated_async_exports_release_terminal_resources_and_close_cleanly(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    """Cada resultado terminal libera las referencias retenidas por el widget."""
    terminal_calls: list[str] = []
    outcomes = iter(("success", "failed", "cancelled"))

    def execute(_request: object, cancelled: object) -> ExportResult:
        outcome = next(outcomes)
        if outcome == "failed":
            raise RuntimeError("synthetic failure")
        if outcome == "cancelled":
            while not cancelled():  # type: ignore[operator]
                pass
        return _result()

    widget = ExportAssistantWidget(
        executor=execute,  # type: ignore[arg-type]
        on_terminal=lambda: terminal_calls.append("terminal"),
    )
    _configure(widget, tmp_path / "repeated.json")
    monkeypatch.setattr(widget, "_show_export_completed", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)

    for outcome in ("success", "failed", "cancelled"):
        if outcome == "cancelled":

            def cancel_and_close() -> None:
                widget._request_cancel()
                widget.close()

            QTimer.singleShot(0, cancel_and_close)
        widget._execute()
        _wait_until(application, lambda: widget._active_export_generation is None)
        assert widget._export_jobs == {}
        assert widget._cancel_token is None

    application.processEvents()

    assert terminal_calls == ["terminal", "terminal", "terminal"]
    assert widget._export_jobs == {}


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
    _wait_until(application, lambda: len(dialogs) == 1)

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
    _wait_until(application, lambda: len(messages) == 1)

    assert len(messages) == 1
    assert widget._last_failure is not None
    assert widget._last_failure.exception_type == "RuntimeError"
    assert "José Muñoz" in widget._last_failure.message
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


def test_overwrite_rejection_precedes_publication_preflight(application, tmp_path, monkeypatch):
    calls = []
    widget = ExportAssistantWidget(
        executor=lambda *args: calls.append("export"),
        preflight=lambda request: calls.append("publish") or request,
    )
    destination = tmp_path / "existing.json"
    destination.write_text("original", encoding="utf-8")
    _configure(widget, destination)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    widget._execute()
    assert calls == []
    assert destination.read_text(encoding="utf-8") == "original"
    assert widget._active_export_generation is None
    widget.deleteLater()
