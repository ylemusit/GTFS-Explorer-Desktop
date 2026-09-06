from __future__ import annotations

import tomllib
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel

from gtfs_explorer import __version__
from gtfs_explorer.infrastructure.exporting import json_exporter
from gtfs_explorer.infrastructure.logging import diagnostic_identity_context
from gtfs_explorer.presentation.desktop.about import AboutDialog
from gtfs_explorer.presentation.desktop.help import HelpCatalog, HelpDialog
from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.presentation.desktop.overview.widget import FeedOverviewWidget
from gtfs_explorer.presentation.desktop.startup_intro import StartupIntroDialog
from gtfs_explorer.product import (
    IDENTITY,
    PRODUCT_VERSION,
    runtime_architecture,
    runtime_build_id,
)


def test_product_identity_has_complete_and_consistent_metadata() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]

    assert IDENTITY.name == "GTFS Explorer Desktop"
    assert IDENTITY.edition == IDENTITY.copyright_year == 2026
    assert IDENTITY.author == "Yeison Arbey Carrillo Lemus"
    assert IDENTITY.rights_notice == "Todos los derechos reservados."
    assert IDENTITY.executable_name == "GTFS Explorer.exe"
    assert IDENTITY.install_directory_name == "GTFS Explorer"
    assert IDENTITY.start_menu_directory_name == "GTFS Explorer"
    assert IDENTITY.shortcut_name == "GTFS Explorer Desktop.lnk"
    assert IDENTITY.portable_directory_name == "GTFS-Explorer"
    assert project["dynamic"] == ["version"]
    assert "version" not in project
    assert metadata["tool"]["setuptools"]["dynamic"]["version"]["attr"] == (
        "gtfs_explorer.product.PRODUCT_VERSION"
    )
    assert IDENTITY.version == PRODUCT_VERSION == __version__ == json_exporter.__version__
    assert IDENTITY.windows_file_version == "0.2.0.0"
    assert IDENTITY.windows_product_version == "0.2.0"


def test_identity_catalog_renders_all_product_metadata() -> None:
    assert t("identity.welcome_window_title", product_name=IDENTITY.name) == (
        "Bienvenido a GTFS Explorer Desktop"
    )
    assert t("identity.edition", edition=IDENTITY.edition) == "Edición 2026"
    assert t("identity.created_by", author=IDENTITY.author).endswith(IDENTITY.author + ".")
    assert IDENTITY.rights_notice in t(
        "identity.copyright",
        year=IDENTITY.copyright_year,
        author=IDENTITY.author,
        rights_notice=IDENTITY.rights_notice,
    )


def test_identity_is_used_by_visible_product_surfaces(application: QApplication) -> None:
    intro = StartupIntroDialog()
    overview = FeedOverviewWidget(lambda: None)
    help_dialog = HelpDialog(HelpCatalog.load_default())
    about = AboutDialog(Path("C:/Users/example/AppData/Local/GTFS Explorer"), build_id="build-test")

    assert intro.windowTitle() == t("identity.welcome_window_title", product_name=IDENTITY.name)
    assert overview._welcome.title() == f"{IDENTITY.name} · Edición {IDENTITY.edition}"
    assert help_dialog.windowTitle() == f"Ayuda de {IDENTITY.name}"
    assert about.windowTitle() == f"Acerca de {IDENTITY.name}"
    assert about._version_label.text() == f"Versión {IDENTITY.version}"
    assert about._build_label.text() == "build-test"
    assert IDENTITY.gtfs_spec_revision in about._gtfs_label.text()
    assert runtime_architecture() in about._architecture_label.text()
    texts = "\n".join(label.text() for label in intro.findChildren(QLabel))
    assert IDENTITY.author in texts
    assert IDENTITY.rights_notice in texts
    assert IDENTITY.version in texts

    intro.deleteLater()
    overview.deleteLater()
    help_dialog.deleteLater()
    about.deleteLater()
    application.processEvents()


def test_build_id_never_exposes_arbitrary_environment_text() -> None:
    assert runtime_build_id({}) == "local"
    assert runtime_build_id({"GTFS_EXPLORER_BUILD_ID": "build-2026.08"}) == "build-2026.08"
    assert runtime_build_id({"GTFS_EXPLORER_BUILD_ID": "token=secret"}) == "local"


def test_diagnostics_carry_the_same_identity_as_the_ui() -> None:
    context = diagnostic_identity_context()

    assert context == {
        "product": IDENTITY.name,
        "version": IDENTITY.version,
        "build_id": runtime_build_id(),
        "gtfs_spec_revision": IDENTITY.gtfs_spec_revision,
        "architecture": runtime_architecture(),
    }
