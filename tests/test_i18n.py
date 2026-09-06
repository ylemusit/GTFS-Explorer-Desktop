import json
import re
from pathlib import Path

from gtfs_explorer.presentation.desktop.i18n import MESSAGES, pseudo_localize, t

_CATALOG_DIRECTORY = Path("src/gtfs_explorer/resources/i18n")
_CATALOG_FILES = ("es.json", "en.json", "de-DE.json", "ja-JP.json", "zh-CN.json")
_PLACEHOLDER = re.compile(r"\{[^{}]+\}")


def test_spanish_catalog_has_unique_non_empty_keys() -> None:
    assert MESSAGES
    assert all(key.strip() and value.strip() for key, value in MESSAGES.items())


def test_missing_translation_key_fails_early() -> None:
    try:
        t("does.not.exist")
    except KeyError as error:
        assert "Falta la clave i18n" in str(error)
    else:
        raise AssertionError("Una clave inexistente debe ser visible en pruebas.")


def test_pseudo_localization_marks_and_expands_text() -> None:
    source = t("settings.choose_map")
    localized = pseudo_localize(source)
    assert localized.startswith("［") and localized.endswith("］")
    assert len(localized) > len(source)


def test_dialog_catalog_keeps_unicode_filters_and_has_no_known_mojibake() -> None:
    required = {
        "dialog.open_project_title",
        "dialog.import_file_filter",
        "dialog.pmtiles_filter",
        "dialog.filter_json",
        "dialog.filter_geojson",
        "dialog.filter_csv",
        "dialog.filter_gtfs",
        "dialog.error_message",
        "export.format_mini_gtfs",
    }
    assert required <= MESSAGES.keys()
    assert t("dialog.import_file_filter") == (
        "GTFS (*.zip);;CSV/TXT compatible (*.csv *.txt);;Todos los archivos (*)"
    )
    assert "importación" in t("dialog.confirm_import_title")

    source_files = (
        Path("packaging/nsis/installer.nsi"),
        Path("tools/build_installer.py"),
        Path("src/gtfs_explorer/resources/i18n/es.json"),
    )
    for path in source_files:
        content = path.read_text(encoding="utf-8-sig")
        assert all(token not in content for token in ("Ã", "Â", "�"))


def test_all_interface_catalogs_have_exact_key_parity_and_final_values() -> None:
    catalogs = {
        filename: json.loads((_CATALOG_DIRECTORY / filename).read_text(encoding="utf-8"))[
            "messages"
        ]
        for filename in _CATALOG_FILES
    }
    all_keys = set(catalogs["es.json"])
    for filename, messages in catalogs.items():
        assert set(messages) == all_keys, filename
        assert all(value.strip() for value in messages.values()), filename
        assert all(value != key for key, value in messages.items()), filename
        assert all(
            marker not in value
            for value in messages.values()
            for marker in ("TODO", "TRANSLATE_ME")
        ), filename
        assert all(
            sorted(_PLACEHOLDER.findall(value))
            == sorted(_PLACEHOLDER.findall(catalogs["es.json"][key]))
            for key, value in messages.items()
        ), filename


def test_secondary_catalogs_do_not_expose_spanish_for_representative_ui_copy() -> None:
    catalogs = {
        filename: json.loads((_CATALOG_DIRECTORY / filename).read_text(encoding="utf-8"))[
            "messages"
        ]
        for filename in _CATALOG_FILES
    }
    representative_keys = (
        "action.new_project",
        "editor.start_editing",
        "editor.workspace_services",
        "editor.visibility_many_routes_question",
        "validation.no_issues",
    )
    for filename in _CATALOG_FILES[1:]:
        assert all(
            catalogs[filename][key] != catalogs["es.json"][key] for key in representative_keys
        ), filename
