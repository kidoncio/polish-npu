"""Pill strings, picked from the desktop locale (Portuguese for pt*, else English).

Standard library only: imported by both the daemon and the pill.
"""
from collections.abc import Mapping

STRINGS = {
    "en": {
        "working": "Polishing…",
        "done": "Done",
        "copied": "Copied — Ctrl+V",
        "kept": "Would change information — kept the original",
        "nothing": "Nothing selected",
        "too_long": "Text too long",
        "no_keys": "Can't simulate keys (/dev/uinput)",
        "error": "Error",
    },
    "pt": {
        "working": "Melhorando…",
        "done": "Pronto",
        "copied": "Copiado — Ctrl+V",
        "kept": "Mudaria informação — mantive o original",
        "nothing": "Nada selecionado",
        "too_long": "Texto longo demais",
        "no_keys": "Sem acesso ao teclado virtual (/dev/uinput)",
        "error": "Erro",
    },
}


def strings_for(env: Mapping[str, str]) -> dict[str, str]:
    # Same precedence as gettext: LC_ALL > LC_MESSAGES > LANG.
    locale = env.get("LC_ALL") or env.get("LC_MESSAGES") or env.get("LANG") or ""
    return STRINGS.get(locale[:2].lower(), STRINGS["en"])
