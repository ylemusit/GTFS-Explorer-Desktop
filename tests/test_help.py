"""Contrato del manual integrado y de su presentación local."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.presentation.desktop.help import HelpCatalog, HelpDialog


def test_manual_local_has_flows_principales_and_searches_without_network() -> None:
    catalog = HelpCatalog.load_default()

    assert {"inicio", "importar", "explorar", "validacion", "exportar", "mapas"} <= {
        topic.topic_id for topic in catalog.search("")
    }
    assert [topic.topic_id for topic in catalog.search("superiores 24")] == ["horas-mayores-24"]
    assert catalog.resolve("validation/ANY_PUBLIC_CODE").topic_id == "validation/reglas"
    assert "http" not in " ".join(topic.body for topic in catalog.search("")).casefold()


def test_all_public_schedule_rule_codes_resolve_to_local_help() -> None:
    specification = load_schedule_spec(Path("schemas/gtfs_schedule/2026-04-27/spec.json"))
    catalog = HelpCatalog.load_default()

    rule_ids = {file.rule_id for file in specification.files.values()} | {
        field.rule_id for file in specification.files.values() for field in file.fields.values()
    }

    assert rule_ids
    assert all(
        catalog.resolve(f"validation/{rule_id}").topic_id == "validation/reglas"
        for rule_id in rule_ids
    )


def test_help_dialog_escapes_content_before_presenting_html(application: QApplication) -> None:
    catalog = HelpCatalog.load_default()
    dialog = HelpDialog(catalog, "explorar")

    assert dialog._body.toPlainText().startswith("Explorar rutas, viajes y horarios")
    assert "<script>" not in dialog._body.toHtml()
    dialog._search.setText("PMTiles")
    assert dialog._topics.count() == 1
    assert dialog._topics.item(0).text() == "Mapas offline"
    dialog.deleteLater()
    application.processEvents()
