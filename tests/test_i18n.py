"""Tests for the i18n module — string catalogs, fallback, lang detection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from reverse_image_search_bot.i18n import (
    _CATALOG,
    _flatten,
    available_languages,
    lang,
    t,
)

# ---------------------------------------------------------------------------
# _flatten
# ---------------------------------------------------------------------------


class TestFlatten:
    def test_flat_dict(self):
        assert _flatten({"a": "1", "b": "2"}) == {"a": "1", "b": "2"}

    def test_nested_dict(self):
        data = {"x": {"y": "z"}}
        assert _flatten(data) == {"x.y": "z"}

    def test_deeply_nested(self):
        data = {"a": {"b": {"c": "deep"}}}
        assert _flatten(data) == {"a.b.c": "deep"}

    def test_mixed_nesting(self):
        data = {"top": "val", "nested": {"inner": "val2"}}
        result = _flatten(data)
        assert result == {"top": "val", "nested.inner": "val2"}

    def test_prefix(self):
        data = {"key": "value"}
        assert _flatten(data, prefix="pre") == {"pre.key": "value"}

    def test_empty_dict(self):
        assert _flatten({}) == {}

    def test_non_string_values_cast(self):
        data = {"num": 42, "flag": True}
        result = _flatten(data)
        assert result == {"num": "42", "flag": "True"}

    def test_multiple_siblings(self):
        data = {"section": {"a": "1", "b": "2", "c": "3"}}
        result = _flatten(data)
        assert result == {"section.a": "1", "section.b": "2", "section.c": "3"}


# ---------------------------------------------------------------------------
# t() — translation lookup
# ---------------------------------------------------------------------------


class TestT:
    def test_english_key(self):
        result = t("commands.ban_usage", "en")
        assert "Usage:" in result and "/ban" in result

    def test_default_lang_is_english(self):
        assert t("commands.ban_usage") == t("commands.ban_usage", "en")

    def test_known_lang(self):
        result = t("commands.ban_usage", "de")
        assert "Verwendung:" in result

    def test_fallback_to_english_for_unknown_lang(self):
        result = t("commands.ban_usage", "xx")
        assert result == t("commands.ban_usage", "en")

    def test_missing_key_returns_key(self):
        assert t("nonexistent.key.here") == "nonexistent.key.here"

    def test_missing_key_unknown_lang_returns_key(self):
        assert t("nonexistent.key", "xx") == "nonexistent.key"

    def test_kwargs_substitution(self):
        result = t("search.creating_url", "en", engine="Google")
        assert "Google" in result

    def test_kwargs_multiple(self):
        result = t("search.results.rate_limit", "en", engine="SauceNAO", period="Daily")
        assert "SauceNAO" in result
        assert "Daily" in result

    def test_extra_kwargs_ignored(self):
        """str.format ignores extra kwargs — t() should not crash."""
        result = t("commands.ban_usage", "en", nonexistent_placeholder="oops")
        assert "/ban" in result

    def test_missing_required_kwarg_raises(self):
        """If a required placeholder is missing from kwargs, KeyError is raised."""
        with pytest.raises(KeyError):
            # Provide a wrong kwarg so kwargs is truthy and .format() runs,
            # but the required {engine} placeholder is missing
            t("search.creating_url", "en", wrong_key="x")

    def test_no_kwargs_skips_formatting(self):
        """When called without kwargs, t() returns raw string with {placeholders} intact."""
        result = t("search.creating_url", "en")
        assert "{engine}" in result

    def test_newlines_preserved(self):
        """TOML \\n sequences should appear as literal newlines in the result."""
        result = t("start.group", "en")
        assert "\n" in result

    def test_html_preserved(self):
        result = t("settings.title", "en")
        assert "<b>" in result and "</b>" in result

    def test_emoji_preserved(self):
        result = t("search.searching", "en")
        assert "⏳" in result

    def test_quotes_in_toml(self):
        """Escaped quotes in TOML should resolve correctly."""
        result = t("settings.disabled_reasons.button_engines", "en")
        assert '"' in result  # contains literal quote

    def test_empty_string_key_returns_key(self):
        assert t("") == ""

    def test_all_languages_have_english_keys(self):
        """Every key in en.toml must exist in all other languages."""
        en_keys = set(_CATALOG.get("en", {}).keys())
        for lang_code, strings in _CATALOG.items():
            if lang_code == "en":
                continue
            missing = en_keys - set(strings.keys())
            assert not missing, f"{lang_code} missing keys: {missing}"

    def test_no_extra_keys_in_translations(self):
        """Non-English catalogs should not have keys absent from English."""
        en_keys = set(_CATALOG.get("en", {}).keys())
        for lang_code, strings in _CATALOG.items():
            if lang_code == "en":
                continue
            extra = set(strings.keys()) - en_keys
            assert not extra, f"{lang_code} has extra keys: {extra}"

    def test_format_placeholders_consistent(self):
        """All languages must use the same {placeholders} as English."""
        import re

        placeholder_re = re.compile(r"\{(\w+)\}")
        en_strings = _CATALOG.get("en", {})
        for lang_code, strings in _CATALOG.items():
            if lang_code == "en":
                continue
            for key, en_text in en_strings.items():
                en_placeholders = set(placeholder_re.findall(en_text))
                if not en_placeholders:
                    continue
                lang_text = strings.get(key, "")
                lang_placeholders = set(placeholder_re.findall(lang_text))
                assert en_placeholders == lang_placeholders, (
                    f"{lang_code}.{key}: placeholders {lang_placeholders} != en {en_placeholders}"
                )

    def test_empty_value_falls_back_to_english(self):
        """If a translation value is empty string, t() should fall back to English."""
        # Simulate by temporarily injecting an empty value
        original = _CATALOG.get("de", {}).get("commands.ban_usage")
        try:
            _CATALOG.setdefault("de", {})["commands.ban_usage"] = ""
            result = t("commands.ban_usage", "de")
            # Empty string is falsy, so `or` falls through to English
            assert result == t("commands.ban_usage", "en")
        finally:
            if original is not None:
                _CATALOG["de"]["commands.ban_usage"] = original


# ---------------------------------------------------------------------------
# lang() — language detection from Update
# ---------------------------------------------------------------------------


class TestLang:
    def _make_update(self, chat_id: int | None = None, language_code: str | None = None):
        update = MagicMock()
        if chat_id is not None:
            update.effective_chat.id = chat_id
        else:
            update.effective_chat = None
        if language_code is not None:
            update.effective_user.language_code = language_code
        else:
            update.effective_user = None
        return update

    def _patch_chatconfig(self, language: str | None = None):
        """Return a context manager that patches ChatConfig in the i18n module's lazy import."""
        cfg = MagicMock()
        cfg.language = language
        MockClass = MagicMock(return_value=cfg)
        # lang() does `from reverse_image_search_bot.config import ChatConfig` lazily,
        # so we patch it in the config package's namespace.
        return patch("reverse_image_search_bot.config.ChatConfig", MockClass), MockClass

    def test_chatconfig_override(self):
        patcher, _MockClass = self._patch_chatconfig("ja")
        with patcher:
            update = self._make_update(chat_id=123, language_code="en")
            assert lang(update) == "ja"

    def test_chatconfig_none_falls_to_user_lang(self):
        patcher, _ = self._patch_chatconfig(None)
        with patcher:
            update = self._make_update(chat_id=123, language_code="de")
            assert lang(update) == "de"

    def test_user_lang_with_region(self):
        """e.g. 'zh-hans' or 'pt-BR' should map to base code."""
        patcher, _ = self._patch_chatconfig(None)
        with patcher:
            update = self._make_update(chat_id=123, language_code="zh-hans")
            assert lang(update) == "zh"

    def test_unsupported_user_lang_falls_to_en(self):
        patcher, _ = self._patch_chatconfig(None)
        with patcher:
            update = self._make_update(chat_id=123, language_code="ko")
            assert lang(update) == "en"

    def test_no_user_falls_to_en(self):
        patcher, _ = self._patch_chatconfig(None)
        with patcher:
            update = self._make_update(chat_id=123, language_code=None)
            assert lang(update) == "en"

    def test_no_chat_no_user(self):
        patcher, MockClass = self._patch_chatconfig(None)
        with patcher:
            update = self._make_update(chat_id=None, language_code=None)
            assert lang(update) == "en"
            MockClass.assert_not_called()

    def test_no_chat_with_user_lang(self):
        patcher, MockClass = self._patch_chatconfig(None)
        with patcher:
            update = self._make_update(chat_id=None, language_code="ru")
            assert lang(update) == "ru"
            MockClass.assert_not_called()

    def test_empty_language_code(self):
        patcher, _ = self._patch_chatconfig(None)
        with patcher:
            update = self._make_update(chat_id=123, language_code="")
            # empty string split("-")[0] == "", not in catalog -> "en"
            assert lang(update) == "en"

    def test_chatconfig_empty_string_language(self):
        """Empty string is falsy, should fall through to user lang detection."""
        patcher, _ = self._patch_chatconfig("")
        with patcher:
            update = self._make_update(chat_id=123, language_code="es")
            assert lang(update) == "es"


# ---------------------------------------------------------------------------
# available_languages
# ---------------------------------------------------------------------------


class TestAvailableLanguages:
    def test_returns_list(self):
        result = available_languages()
        assert isinstance(result, list)

    def test_contains_english(self):
        assert "en" in available_languages()

    def test_sorted(self):
        langs = available_languages()
        assert langs == sorted(langs)

    def test_expected_count(self):
        # We ship 8 TOML files: ar, de, en, es, it, ja, ru, zh
        assert len(available_languages()) == 10

    def test_all_expected_present(self):
        expected = {"ar", "de", "en", "es", "fr", "it", "ja", "pt", "ru", "zh"}
        assert set(available_languages()) == expected


# ---------------------------------------------------------------------------
# Catalog integrity
# ---------------------------------------------------------------------------


class TestCatalogIntegrity:
    def test_catalog_loaded(self):
        assert len(_CATALOG) > 0

    def test_english_is_canonical(self):
        assert "en" in _CATALOG
        assert len(_CATALOG["en"]) > 0

    def test_no_empty_english_values(self):
        for key, value in _CATALOG["en"].items():
            assert value.strip(), f"en.{key} is empty"

    def test_all_toml_files_loaded(self):
        from pathlib import Path

        toml_dir = Path(__file__).parent.parent / "reverse_image_search_bot" / "i18n"
        toml_files = {f.stem for f in toml_dir.glob("*.toml")}
        assert toml_files == set(_CATALOG.keys())

    def test_bot_commands_section_exists(self):
        """Every language must have the bot_commands keys for setMyCommands."""
        required = {"bot_commands.search", "bot_commands.settings", "bot_commands.help", "bot_commands.start"}
        for lang_code, strings in _CATALOG.items():
            missing = required - set(strings.keys())
            assert not missing, f"{lang_code} missing bot_commands keys: {missing}"
