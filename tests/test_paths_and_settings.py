"""Pruebas de rutas de aplicación y settings locales de T005."""

from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_explorer.application.settings import (
    Settings,
    load_settings,
    relative_project_path,
    save_settings,
)
from gtfs_explorer.infrastructure.filesystem.paths import (
    WorkspaceSelectionRequired,
    application_resource_path,
    resolve_application_paths,
)


def test_installed_paths_use_local_app_data_with_spaces_and_unicode(tmp_path: Path) -> None:
    executable = tmp_path / "Aplicación ñ" / "gtfs-explorer.exe"
    executable.parent.mkdir()
    executable.touch()
    paths = resolve_application_paths(executable, local_app_data=tmp_path / "Datos locales ü")

    assert paths.is_portable is False
    assert paths.workspace == tmp_path / "Datos locales ü" / "GTFS Explorer"
    assert paths.workspace != Path.cwd()


def test_portable_uses_workspace_next_to_executable_when_usable(tmp_path: Path) -> None:
    executable = tmp_path / "portable" / "gtfs-explorer.exe"
    executable.parent.mkdir()
    executable.touch()
    (executable.parent / "portable.flag").touch()

    paths = resolve_application_paths(
        executable, portable_workspace_is_usable=lambda _path, _free: True
    )

    assert paths.is_portable is True
    assert paths.workspace == executable.parent / "workspace"


def test_portable_requires_user_selection_when_workspace_is_not_usable(tmp_path: Path) -> None:
    executable = tmp_path / "portable" / "gtfs-explorer.exe"
    executable.parent.mkdir()
    executable.touch()
    (executable.parent / "portable.flag").touch()

    with pytest.raises(WorkspaceSelectionRequired):
        resolve_application_paths(
            executable, portable_workspace_is_usable=lambda _path, _free: False
        )


def test_settings_store_only_relative_project_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "espacio ñ"
    project = workspace / "projects" / "demo" / "project.json"
    project.parent.mkdir(parents=True)
    project.touch()
    settings_path = workspace / "settings.json"
    relative = relative_project_path(workspace, project)

    save_settings(settings_path, Settings(recent_project_paths=(relative,)))

    assert load_settings(settings_path).recent_project_paths == (relative,)
    with pytest.raises(ValueError):
        relative_project_path(workspace, tmp_path / "externo" / "project.json")


def test_settings_roundtrip_preserves_explore_splitter_state(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    state = b"qt-splitter-state"

    save_settings(settings_path, Settings(explore_splitter_state=state))

    assert load_settings(settings_path).explore_splitter_state == state


def test_settings_rejects_corrupt_explore_splitter_state(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        '{"version": 1, "recent_project_paths": [], "explore_splitter_state": "%%%"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_settings(settings_path)


def test_application_resources_do_not_depend_on_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(Path.cwd().anchor)

    assert application_resource_path("schemas/gtfs_schedule/2026-04-27/spec.json").is_file()


def test_application_resources_detect_standalone_without_frozen_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "Aplicación portable" / "GTFS Explorer.exe"
    resource = executable.parent / "schemas" / "spec.json"
    resource.parent.mkdir(parents=True)
    resource.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("sys.executable", str(executable))
    monkeypatch.delattr("sys.frozen", raising=False)

    assert application_resource_path("schemas/spec.json") == resource
