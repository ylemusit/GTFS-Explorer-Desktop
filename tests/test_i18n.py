from pathlib import Path

from gtfs_explorer.presentation.desktop.i18n import MESSAGES, pseudo_localize, t


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
