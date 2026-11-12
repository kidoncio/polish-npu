"""Pill strings follow the desktop locale."""
from polish.i18n import STRINGS, strings_for

KEYS = {"working", "done", "copied", "kept", "nothing", "too_long", "no_keys", "error"}


def test_portuguese_locale():
    assert strings_for({"LANG": "pt_BR.UTF-8"})["working"] == "Melhorando…"


def test_english_is_the_fallback():
    assert strings_for({})["kept"] == "Would change information — kept the original"


def test_lc_all_wins_over_lang():
    assert strings_for({"LANG": "en_US.UTF-8", "LC_ALL": "pt_BR.UTF-8"})["done"] == "Pronto"


def test_both_languages_have_every_key():
    assert set(STRINGS["en"]) == set(STRINGS["pt"]) == KEYS
