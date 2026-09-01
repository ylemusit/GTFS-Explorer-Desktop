"""Regresión del resultado entero de QMessageBox.question en importación."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from zipfile import ZipFile

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.presentation.desktop.main_window import MainWindow


def _small_gtfs_zip(tmp_path: Path) -> Path:
    specification = json.loads(
        Path("tests/fixtures/specs/mini_gtfs_contract.json").read_text(encoding="utf-8")
    )
    source_directory = tmp_path / "small-gtfs"
    source_directory.mkdir()
    for filename, table in specification["tables"].items():
        with (source_directory / filename).open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=table["headers"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(table["rows"])

    archive = tmp_path / "small-gtfs.zip"
    with ZipFile(archive, "w") as output:
        for entry in sorted(source_directory.iterdir()):
            output.write(entry, entry.name)
    return archive


def _click_real_message_box(application: QApplication, button: QMessageBox.StandardButton) -> None:
    """Pulsa un botón de un QMessageBox real dentro de su modal event loop."""

    def click() -> None:
        for widget in application.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                target = widget.button(button)
                assert target is not None
                target.click()
                return
        QTimer.singleShot(10, click)

    QTimer.singleShot(0, click)


def _click_import_option(application: QApplication, label: str) -> None:
    def click() -> None:
        for widget in application.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                for button in widget.buttons():
                    if button.text() == label:
                        button.click()
                        return
        QTimer.singleShot(10, click)

    QTimer.singleShot(0, click)


def test_real_message_box_yes_uses_folder_selector(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    window = MainWindow()
    selected_folder = tmp_path / "selected-folder"
    selected_folder.mkdir()
    selected: list[Path] = []
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(selected_folder),
    )
    monkeypatch.setattr(window, "_request_import", lambda source: selected.append(source.path))
    _click_real_message_box(application, QMessageBox.StandardButton.Yes)

    window._choose_import_source()

    assert selected == [selected_folder]
    window.close()


def test_real_message_box_no_uses_file_selector(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    window = MainWindow()
    archive = _small_gtfs_zip(tmp_path)
    selected: list[Path] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(archive), "GTFS (*.zip)"),
    )
    monkeypatch.setattr(window, "_request_import", lambda source: selected.append(source.path))
    _click_import_option(application, "ZIP GTFS / Mini-GTFS")

    window._choose_import_source()

    assert selected == [archive]
    window.close()


def test_real_message_box_csv_txt_uses_explicit_csv_filter(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    window = MainWindow()
    csv_file = tmp_path / "routes.txt"
    csv_file.write_text("route_id\nR1\n", encoding="utf-8")
    selected: list[Path] = []
    filters: list[str] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda _parent, _title, _directory, filter: (
            filters.append(filter) or (str(csv_file), filter)
        ),
    )
    monkeypatch.setattr(window, "_request_import", lambda source: selected.append(source.path))
    _click_import_option(application, "CSV/TXT")

    window._choose_import_source()

    assert selected == [csv_file]
    assert filters == ["CSV/TXT compatible (*.csv *.txt)"]
    window.close()


def test_import_confirmation_explains_source_and_next_step(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    window = MainWindow()
    window.project_opened()
    source = InputSource(tmp_path / "feed.zip", InputSourceKind.ARCHIVE)
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, _title, message, *_args: messages.append(message)
        or QMessageBox.StandardButton.No,
    )

    window._request_import(source)

    assert "un ZIP GTFS" in messages[0]
    assert str(source.path) in messages[0]
    assert "preflight" not in messages[0].casefold()
    assert "validará localmente" in messages[0]
    window.close()


def test_real_message_box_yes_confirmation_starts_import_once(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    window = MainWindow()
    window.project_opened()
    archive = _small_gtfs_zip(tmp_path)
    started: list[InputSource] = []
    monkeypatch.setattr(window, "start_import", lambda source: started.append(source))
    _click_real_message_box(application, QMessageBox.StandardButton.Yes)

    window._request_import(InputSource(archive, InputSourceKind.ARCHIVE))

    assert started == [InputSource(archive, InputSourceKind.ARCHIVE)]
    window.close()


def test_real_message_box_no_confirmation_does_not_start_import(
    application: QApplication, tmp_path: Path, monkeypatch
) -> None:
    window = MainWindow()
    window.project_opened()
    archive = _small_gtfs_zip(tmp_path)
    started: list[InputSource] = []
    monkeypatch.setattr(window, "start_import", lambda source: started.append(source))
    _click_real_message_box(application, QMessageBox.StandardButton.No)

    window._request_import(InputSource(archive, InputSourceKind.ARCHIVE))

    assert started == []
    window.close()
