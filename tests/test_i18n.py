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
