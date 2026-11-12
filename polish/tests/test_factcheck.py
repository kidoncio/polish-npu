"""Deterministic fact check: a rewrite must keep every fact of the original."""
from polish.factcheck import check, detect_language

MEETING = ("Pessoal, lembrando que amanha a reuniao de planejamento foi movida pras 14h30 por causa do feriado, "
           "quem nao puder avisa o João ate hoje 18h. link: https://meet.example.com/abc-defg")


def test_faithful_rewrite_passes():
    good = ("Pessoal, lembrando que a reunião de planejamento de amanhã foi movida para as 14h30 por causa do feriado. "
            "Quem não puder, avise o João até hoje às 18h. Link: https://meet.example.com/abc-defg")
    assert check(MEETING, good) == []


def test_tomorrow_turned_into_today_is_caught():  # the real Qwen3-8B failure from the spike
    bad = ("Pessoal, lembrando que a reunião de planejamento foi movida para as 14h30 hoje por causa do feriado. "
           "Quem não puder, avise o João até hoje às 18h. Link: https://meet.example.com/abc-defg")
    assert "day:amanha" in check(MEETING, bad)


def test_numbers_compare_by_digit_groups():
    assert check("migration 2024_11_03 before the 3pm demo", "Migration 2024_11_03, before the 3 PM demo.") == []
    assert "number:30" in check("às 14h30", "às 14h")


def test_url_mention_channel_code_and_emoji_are_verbatim():
    orig = "@ana veja #infra `make up` https://x.io/a?b=1 👍"
    assert check(orig, "@ana, veja #infra: `make up` https://x.io/a?b=1 👍") == []
    assert "verbatim:https://x.io/a?b=1" in check(orig, "@ana veja #infra `make up` 👍")


def test_dropped_negation_is_caught():
    assert "negation:1" in check("não precisa revisar hoje", "Precisa revisar hoje.")
    assert check("I can't make it", "I cannot make it.") == []


def test_names_mid_sentence_must_survive():
    assert "name:joao" in check("avisa o João até hoje", "Avise até hoje.")
    assert check("oi Ana, tudo bem?", "Oi, Ana! Tudo bem?") == []


def test_translation_is_caught():
    assert "language:pt>en" in check("consegue dar uma olhada hoje? o cliente está cobrando",
                                     "Can you take a look today? The client is asking.")


def test_language_mixed_pt_is_pt():
    assert detect_language("o deploy falhou de novo no staging por causa da migration, consegue ver?") == "pt"


def test_plain_word_loss_is_a_known_gap():  # "again" dropped: documented limitation, not caught
    assert check("the deploy failed again on staging", "The deploy failed on staging.") == []
