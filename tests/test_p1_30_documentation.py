"""Contratos críticos de la documentación y ayuda de usuario de P1-30."""

from __future__ import annotations

import json
import re
from pathlib import Path

from gtfs_explorer.presentation.desktop.help import HelpCatalog
from gtfs_explorer.product import IDENTITY

ROOT = Path(__file__).parents[1]


def test_user_guide_covers_current_journeys_without_future_claims() -> None:
    guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    required = (
        "Crear un proyecto",
        "Importar GTFS",
        "IMPORT COMPLETED + INVALID",
        "Validación",
        "RAW",
        "Mapas offline",
        "Mini-GTFS",
        "Historial",
        "Recovery",
        "Privacidad",
        "Accesibilidad",
        "F1",
    )
    assert all(section in guide for section in required)
    assert "KML y KMZ no son formatos disponibles" in guide
    assert "no se sube a Internet" in guide
    assert not re.search(r"C:\\Users\\[^`\n]+", guide, re.IGNORECASE)
    assert "editar rutas" not in guide.casefold()


def test_help_catalog_matches_user_contract_and_is_local() -> None:
    catalog = HelpCatalog.load_default()
    ids = {topic.topic_id for topic in catalog.search("")}
    assert {
        "inicio",
        "importar",
        "estados",
        "raw",
        "validacion",
        "mapas",
        "exportar",
        "recovery",
    } <= ids
    content = " ".join(topic.body for topic in catalog.search(""))
    for expected in (
        "VALID",
        "INVALID",
        "FAILED",
        "AUTO",
        "OFFLINE",
        "ONLINE",
        "route_id",
        "Mini-GTFS",
    ):
        assert expected in content
    assert "KML y KMZ no están disponibles" in content
    assert "http" not in content.casefold()


def test_help_packaging_manifest_points_to_existing_offline_files() -> None:
    manifest_path = ROOT / "docs" / "HELP_PACKAGING_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == 1
    assert manifest["offline"] is True
    for entry in manifest["files"]:
        if entry["source"] == "gtfs_explorer/resources/help/index.json":
            assert (ROOT / "src" / entry["source"]).is_file()
        else:
            assert (ROOT / entry["source"]).is_file()


def test_user_guide_uses_canonical_identity_reference() -> None:
    guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    assert IDENTITY.name == "GTFS Explorer Desktop"
    assert "0.1.0" not in guide
