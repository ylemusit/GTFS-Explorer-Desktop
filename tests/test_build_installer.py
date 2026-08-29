from __future__ import annotations

import codecs
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
    script = Path("packaging/nsis/installer.nsi").read_text(encoding="utf-8-sig")

    assert "RequestExecutionLevel user" in script
    assert 'InstallDir "$LOCALAPPDATA\\Programs\\${PRODUCT_INSTALL_DIRECTORY}"' in script
    assert "WriteRegStr HKCU" in script
    assert "CreateShortcut" in script
    assert 'RMDir /r "$LOCALAPPDATA\\GTFS Explorer"' not in script
    assert ".zip" not in script


def test_installer_identity_is_provided_by_the_build_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    command: list[str] = []

    def run(arguments: list[str], **_kwargs: object) -> None:
        command.extend(arguments)

    monkeypatch.setattr(module.subprocess, "run", run)
    module._run_makensis(
        executable="makensis",
        version="0.1.0",
        payload=Path("payload"),
        output=Path("setup.exe"),
    )

    assert f"/DPRODUCT_NAME={module.IDENTITY.name}" in command
    assert f"/DPRODUCT_PUBLISHER={module.IDENTITY.author}" in command
    assert f"/DPRODUCT_FILE_VERSION={module.IDENTITY.windows_file_version}" in command
    assert f"/DPRODUCT_DESCRIPTION={module.IDENTITY.file_description}" in command
    assert f"/DPRODUCT_EDITION={module.IDENTITY.edition}" in command
    assert f"/DPRODUCT_EXECUTABLE={module.IDENTITY.executable_name}" in command
    assert f"/DPRODUCT_INSTALL_DIRECTORY={module.IDENTITY.install_directory_name}" in command
    assert f"/DPRODUCT_START_MENU_DIRECTORY={module.IDENTITY.start_menu_directory_name}" in command
    assert f"/DPRODUCT_SHORTCUT_NAME={module.IDENTITY.shortcut_name}" in command
    script = Path("packaging/nsis/installer.nsi").read_text(encoding="utf-8")
    assert 'VIProductVersion "${PRODUCT_FILE_VERSION}"' in script
    assert 'VIAddVersionKey /LANG=3082 "ProductName"' in script
    assert 'VIAddVersionKey /LANG=3082 "FileVersion"' in script
    assert 'VIAddVersionKey /LANG=3082 "CompanyName"' in script
    assert 'VIAddVersionKey /LANG=3082 "LegalCopyright"' in script
    assert '!define PRODUCT_NAME "GTFS Explorer Desktop"' not in script


def test_nsis_source_is_utf8_unicode_and_keeps_installation_strings_intact() -> None:
    path = Path("packaging/nsis/installer.nsi")
    source = path.read_bytes()

    assert source.startswith(codecs.BOM_UTF8)
    script = source.decode("utf-8-sig")
    assert script.index("Unicode true") < script.index("SetCompressor")
    assert '!insertmacro MUI_LANGUAGE "Spanish"' in script
    assert "Edición" in script
    assert "aplicación" in script
    assert "Ã" not in script and "Â" not in script and "�" not in script
    for define in (
        "PRODUCT_EXECUTABLE",
        "PRODUCT_INSTALL_DIRECTORY",
        "PRODUCT_START_MENU_DIRECTORY",
        "PRODUCT_SHORTCUT_NAME",
    ):
        assert f"${{{define}}}" in script


def test_missing_makensis_is_reported_as_an_explicit_skip(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    monkeypatch.setattr(module, "_resolve_makensis", lambda _executable: None)
    monkeypatch.setattr(module.sys, "argv", ["build_installer.py", "--check-makensis"])

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "SKIPPED / TOOL_NOT_AVAILABLE"
