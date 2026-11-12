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


def test_dropped_again_is_caught():  # the real Qwen3-4B failure from the evaluation
    assert "keyword:again" in check("the deploy failed again on staging", "The deploy failed on staging.")
    assert "keyword:de novo" in check("o build quebrou de novo hj", "O build quebrou hoje.")


def test_keywords_survive_a_synonym():
    assert check("falhou de novo", "Falhou novamente.") == []
    assert check("tbm preciso disso", "Também preciso disso.") == []


def test_plain_word_loss_is_a_known_gap():  # other words are the prompt's job, not the check's
    assert check("the deploy on staging failed", "The deploy failed.") == []


def test_expanded_day_abbreviations_are_the_same_day():
    assert check("consegue olhar hj? se nao amanha", "Consegue olhar hoje? Se não, amanhã.") == []
    assert check("can u check tmrw", "Can you check tomorrow?") == []


# Everyday Brazilian Portuguese that shares words with English (do, me, so, to, for).
PT_CHAT = [
    "se for possível me avisa do deploy, só preciso do PR",
    "me avisa quando o deploy do staging terminar",
    "pode fazer o deploy do hotfix? so precisa do approve do tech lead",
    "to fazendo o refactor do service, me manda o link do ticket",
]


def test_portuguese_chat_with_english_lookalikes_is_portuguese():
    for text in PT_CHAT:
        assert detect_language(text) == "pt", text


def test_english_messages_stay_english():
    for text in ("Can you send me the Q3 report by Friday? Thanks!", "I can't make it to the meeting today",
                 "hey, quick one - the deploy failed again on staging, can you check it before the demo?"):
        assert detect_language(text) == "en", text


def test_translation_of_lookalike_portuguese_is_caught():
    assert "language:pt>en" in check(PT_CHAT[1], "Let me know when the staging deploy is finished.")
