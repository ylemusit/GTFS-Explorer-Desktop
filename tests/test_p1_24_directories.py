"""Regresiones de la política de directorios y preferencias P1-24."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from gtfs_explorer.application.settings import DirectoryPreferences, Settings, load_settings
from gtfs_explorer.infrastructure.filesystem.paths import (
    DirectoryKind,
    resolve_application_paths,
)
from gtfs_explorer.presentation.desktop.exporter.widget import ExportAssistantWidget
from gtfs_explorer.presentation.desktop.main_window import MainWindow


def _paths(tmp_path: Path):
    executable = tmp_path / "Program Files" / "GTFS Explorer" / "gtfs-explorer.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    return resolve_application_paths(
        executable,
        local_app_data=tmp_path / "Datos locales ü",
        documents_directory=tmp_path / "Documentos redirigidos ñ",
    )


def test_default_directories_are_stable_accessible_and_lazy(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    assert paths.projects_directory == (paths.documents_directory / "GTFS Explorer" / "Projects")
    assert paths.imports_directory == paths.documents_directory / "GTFS Explorer" / "Imports"
    assert paths.exports_directory == paths.documents_directory / "GTFS Explorer" / "Exports"
    assert paths.diagnostics_directory == (
        paths.documents_directory / "GTFS Explorer" / "Diagnostics"
    )
    assert paths.maps_directory == paths.workspace / "maps"
    assert paths.maps_directory == paths.application_data_directory / "maps"
    assert paths.projects_directory.is_absolute()
    assert paths.projects_directory != paths.workspace / "projects"
    assert not paths.projects_directory.exists()
    assert not paths.exports_directory.exists()
    assert not paths.diagnostics_directory.exists()

    preferences = DirectoryPreferences(paths)
    assert preferences.initial_directory(DirectoryKind.PROJECTS) == paths.projects_directory
    assert not paths.projects_directory.exists()
    assert preferences.dialog_directory(DirectoryKind.PROJECTS) == paths.projects_directory
    assert paths.projects_directory.is_dir()


def test_known_documents_resolver_and_unicode_paths_are_used(tmp_path: Path) -> None:
    documents = tmp_path / "OneDrive" / "Documentos ñ"
    executable = tmp_path / "app" / "gtfs-explorer.exe"
    executable.parent.mkdir()
    executable.touch()
    called: list[bool] = []

    paths = resolve_application_paths(
        executable,
        local_app_data=tmp_path / "LocalAppData",
        documents_directory_resolver=lambda: called.append(True) or documents,
    )

    assert called == [True]
    assert paths.documents_directory == documents
    assert paths.exports_directory == documents / "GTFS Explorer" / "Exports"
    assert "ñ" in str(paths.exports_directory)


def test_last_directories_persist_and_missing_values_fall_back(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    projects = tmp_path / "projects"
    imports = tmp_path / "imports"
    exports = tmp_path / "exports"
    maps_source = tmp_path / "map-source"
    diagnostics = tmp_path / "diagnostics"
    for directory in (projects, imports, exports, maps_source, diagnostics):
        directory.mkdir()

    preferences = DirectoryPreferences(paths)
    assert preferences.remember(DirectoryKind.PROJECTS, projects)
    assert preferences.remember(DirectoryKind.IMPORTS, imports)
    assert preferences.remember(DirectoryKind.EXPORTS, exports)
    assert preferences.remember(DirectoryKind.PMTILES_IMPORT, maps_source)
    assert preferences.remember(DirectoryKind.DIAGNOSTICS, diagnostics)

    reopened = DirectoryPreferences(paths)
    assert reopened.settings.last_project_dir == projects
    assert reopened.settings.last_import_dir == imports
    assert reopened.settings.last_export_dir == exports
    assert reopened.settings.last_pmtiles_import_dir == maps_source
    assert reopened.settings.last_diagnostic_dir == diagnostics
    assert load_settings(paths.settings_path).last_export_dir == exports
    settings_text = paths.settings_path.read_text(encoding="utf-8")
    assert "exports" in settings_text

    missing = DirectoryPreferences(
        paths,
        settings=Settings(
            last_project_dir=tmp_path / "gone-projects",
            last_import_dir=tmp_path / "gone-imports",
            last_export_dir=tmp_path / "gone-exports",
            last_pmtiles_import_dir=tmp_path / "gone-maps",
            last_diagnostic_dir=tmp_path / "gone-diagnostics",
        ),
        persist=False,
    )
    assert missing.initial_directory(DirectoryKind.PROJECTS) == paths.projects_directory
    assert missing.initial_directory(DirectoryKind.IMPORTS) == paths.imports_directory
    assert missing.initial_directory(DirectoryKind.EXPORTS) == paths.exports_directory
    assert missing.initial_directory(DirectoryKind.PMTILES_IMPORT) == paths.map_imports_directory
    assert missing.initial_directory(DirectoryKind.DIAGNOSTICS) == paths.diagnostics_directory


def test_permission_failure_returns_an_existing_fallback_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    preferences = DirectoryPreferences(paths, persist=False)
    paths.user_documents_directory.mkdir(parents=True)
    original_mkdir = Path.mkdir

    def fail_default(directory: Path, *args: object, **kwargs: object) -> None:
        if directory == paths.exports_directory:
            raise OSError("synthetic permission failure")
        original_mkdir(directory, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_default)

    fallback = preferences.dialog_directory(DirectoryKind.EXPORTS)

    assert fallback == paths.user_documents_directory
    assert fallback.is_dir()


def test_installed_storage_does_not_use_program_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    for directory in (
        paths.application_data_directory,
        paths.projects_directory,
        paths.imports_directory,
        paths.exports_directory,
        paths.diagnostics_directory,
        paths.maps_directory,
    ):
        assert "Program Files" not in str(directory)


@pytest.fixture(autouse=True)
def _replace_web_map(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMap(QWidget):
        def __init__(self, _layers: object, _stop_selected: object) -> None:
            super().__init__()
            self.map_status = "Mapa de prueba."

        def clear(self) -> None:
            pass

        def show_trip(self, _trip_id: str) -> None:
            pass

        def select_stop(self, _stop_id: str) -> None:
            pass

        def set_mode(self, _mode: object) -> str:
            return self.map_status

        def set_managed_map(self, _library: object, _item: object) -> None:
            pass

    monkeypatch.setattr("gtfs_explorer.presentation.desktop.routes.widget.MapWidget", FakeMap)


def test_main_dialogs_use_defaults_and_remember_selected_directories(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    window = MainWindow(application_paths=paths)
    existing_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *args: existing_calls.append(args) or str(project),
    )

    window._choose_new_project()

    assert existing_calls[0][2] == str(paths.projects_directory)
    assert load_settings(paths.settings_path).last_project_dir == project

    window._close_project()
    source = tmp_path / "entrada" / "feed.zip"
    source.parent.mkdir()
    source.write_bytes(b"synthetic")
    open_calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: open_calls.append(args) or (str(source), "GTFS (*.zip)"),
    )
    choices = iter((QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: next(choices))
    requested: list[Path] = []
    monkeypatch.setattr(window, "_request_import", lambda selected: requested.append(selected.path))

    window._choose_import_source()

    assert open_calls[0][2] == str(paths.imports_directory)
    assert requested == [source]
    assert load_settings(paths.settings_path).last_import_dir == source.parent
    window.deleteLater()
    application.processEvents()


def test_cancelled_import_dialog_preserves_last_directory_then_remembers_unicode_selection(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    previous = tmp_path / "José Muñoz" / "anterior"
    previous.mkdir(parents=True)
    preferences = DirectoryPreferences(paths)
    assert preferences.remember(DirectoryKind.IMPORTS, previous)
    assert "José Muñoz" in paths.settings_path.read_text(encoding="utf-8")

    source = tmp_path / "Álvarez" / "entrada.zip"
    source.parent.mkdir()
    source.write_bytes(b"synthetic")
    selections = iter((("", ""), (str(source), "GTFS (*.zip)")))
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: calls.append(args) or next(selections),
    )
    source_kind_choices = iter((QMessageBox.StandardButton.No, QMessageBox.StandardButton.No))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: next(source_kind_choices))
    requested: list[Path] = []
    window = MainWindow(application_paths=paths)
    monkeypatch.setattr(window, "_request_import", lambda selected: requested.append(selected.path))

    window._choose_import_source()

    assert load_settings(paths.settings_path).last_import_dir == previous
    assert calls[0][2] == str(previous)

    window._choose_import_source()

    assert requested == [source]
    assert load_settings(paths.settings_path).last_import_dir == source.parent
    assert calls[1][2] == str(previous)
    window.deleteLater()
    application.processEvents()


def test_export_widget_starts_in_default_and_remembers_chosen_folder(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default = tmp_path / "Documentos" / "GTFS Explorer" / "Exports"
    default.mkdir(parents=True)
    chosen = tmp_path / "otra-carpeta"
    chosen.mkdir()
    calls: list[tuple[object, ...]] = []
    remembered: list[Path] = []
    widget = ExportAssistantWidget(
        default_directory_resolver=lambda: default,
        prepare_default_directory=lambda: default,
        on_destination_directory_used=remembered.append,
    )
    widget._routes.setPlainText("R1")
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args: calls.append(args) or (str(chosen / "salida.json"), "JSON (*.json)"),
    )

    widget._choose_destination()

    assert calls[0][2] == str(default / "gtfs-export-route-R1-json.json")
    assert calls[0][3] == "JSON (*.json)"
    assert remembered == [chosen]
    assert widget._destination.text() == str(chosen / "salida.json")

    widget.deleteLater()
    application.processEvents()
