from __future__ import annotations

import pytest

from gtfs_explorer.presentation.desktop.i18n import (
    current_locale,
    set_locale,
    supported_locales,
    t,
)


@pytest.mark.parametrize("locale", ("es-ES", "en", "de-DE", "ja-JP", "zh-CN"))
def test_supported_locales_translate_editing_and_stop_surface(locale: str) -> None:
    try:
        assert set_locale(locale) == locale
        assert current_locale() == locale
        assert t("editor.start_editing")
        assert t("editor.select_routes_explanation")
        assert t("editor.workspace_properties_description")
        assert t("stop.scheduled_time")
        assert t("map.mode_label")
    finally:
        set_locale("es-ES")


def test_invalid_locale_falls_back_to_english_without_exposing_a_key() -> None:
    try:
        assert set_locale("xx-XX") == "en"
        assert t("editor.start_editing") == "Start editing"
        assert "editor.start_editing" not in t("editor.start_editing")
    finally:
        set_locale("es-ES")


def test_selector_order_is_stable_and_explicit() -> None:
    assert supported_locales() == ("es-ES", "en", "de-DE", "ja-JP", "zh-CN")
