"""Contratos del icono multirresolución de Windows de B5."""

from __future__ import annotations

import struct
from pathlib import Path

from gtfs_explorer.presentation.desktop.icon import application_icon_path


def _ico_sizes(path: Path) -> set[tuple[int, int]]:
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind) == (0, 1)
    sizes: set[tuple[int, int]] = set()
    for offset in range(6, 6 + count * 16, 16):
        width, height = struct.unpack_from("<BB", data, offset)
        sizes.add((width or 256, height or 256))
    return sizes


def test_product_ico_exists_and_contains_expected_sizes() -> None:
    path = Path("src/gtfs_explorer/resources/gtfs_explorer.ico")
    assert application_icon_path() == path.resolve()
    assert _ico_sizes(path) == {
        (16, 16),
        (20, 20),
        (24, 24),
        (32, 32),
        (40, 40),
        (48, 48),
        (64, 64),
        (128, 128),
        (256, 256),
    }


def test_deploy_config_references_product_ico() -> None:
    specification = Path("packaging/portable/pysidedeploy.spec").read_text(encoding="utf-8")
    assert "icon = src/gtfs_explorer/resources/gtfs_explorer.ico" in specification
    assert "--windows-icon-from-ico=src/gtfs_explorer/resources/gtfs_explorer.ico" in specification


def test_nsis_uses_product_ico_for_installer_and_uninstaller() -> None:
    script = Path("packaging/nsis/installer.nsi").read_text(encoding="utf-8-sig")
    assert (
        '!define PRODUCT_ICON "${PAYLOAD_DIR}\\gtfs_explorer\\resources\\gtfs_explorer.ico"'
        in script
    )
    assert '!define MUI_ICON "${PRODUCT_ICON}"' in script
    assert '!define MUI_UNICON "${PRODUCT_ICON}"' in script
    assert 'DisplayIcon" "$INSTDIR\\${PRODUCT_EXECUTABLE}"' in script
    assert (
        'CreateShortcut "$DESKTOP\\${PRODUCT_SHORTCUT_NAME}" '
        '"$INSTDIR\\${PRODUCT_EXECUTABLE}"' in script
    )
