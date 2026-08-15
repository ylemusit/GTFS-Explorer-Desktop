from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest


def _module():
    path = Path("tools/build_installer.py")
    spec = importlib.util.spec_from_file_location("build_installer", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _portable_archive(path: Path, *, safe: bool = True) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        root = "GTFS Explorer Portable/"
        archive.writestr(root + "GTFS Explorer.exe", b"exe")
        archive.writestr(root + "portable.flag", b"")
        archive.writestr(root + "web/map/qt_resources/map_bundle.js", b"")
        if not safe:
            archive.writestr("..\\outside.txt", b"unsafe")


def test_extract_payload_removes_portable_mode_for_installed_app(tmp_path: Path) -> None:
    module = _module()
    archive = tmp_path / "portable.zip"
    _portable_archive(archive)

    payload = module._extract_payload(archive, tmp_path / "stage")

    assert (payload / "GTFS Explorer.exe").is_file()
    assert not (payload / "portable.flag").exists()


def test_extract_payload_rejects_unsafe_archive_members(tmp_path: Path) -> None:
    module = _module()
    archive = tmp_path / "unsafe.zip"
    _portable_archive(archive, safe=False)

    with pytest.raises(RuntimeError, match="rutas no seguras"):
        module._extract_payload(archive, tmp_path / "stage")


def test_nsis_script_keeps_workspace_outside_the_installation() -> None:
    script = Path("packaging/nsis/installer.nsi").read_text(encoding="utf-8")

    assert "RequestExecutionLevel user" in script
    assert 'InstallDir "$LOCALAPPDATA\\Programs\\GTFS Explorer"' in script
    assert "WriteRegStr HKCU" in script
    assert "CreateShortcut" in script
    assert 'RMDir /r "$LOCALAPPDATA\\GTFS Explorer"' not in script
    assert ".zip" not in script
