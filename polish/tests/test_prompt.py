"""Prompt building and model-output cleanup."""
from polish.prompt import EXAMPLES, SYSTEM, build_chat, clean_output, max_new_tokens, reapply_whitespace


PT = "o deploy de hj falhou de novo, vc consegue ver?"
EN = "the deploy failed again today, can you take a look?"


def test_build_chat_ends_with_the_user_text():
    chat = build_chat(PT)
    assert chat[0]["role"] == "system" and chat[0]["content"].startswith(SYSTEM)
    assert chat[-1] == {"role": "user", "content": PT}


def test_build_chat_uses_only_examples_in_the_message_language():
    for text, lang in ((PT, "pt"), (EN, "en")):
        chat = build_chat(text)
        assert len(chat) == 2 + 2 * len(EXAMPLES[lang])
        assert [m["content"] for m in chat[1:-1:2]] == [before for before, _ in EXAMPLES[lang]]


def test_build_chat_names_the_language():
    assert "This message is in Portuguese. Answer in Portuguese." in build_chat(PT)[0]["content"]
    assert "This message is in English. Answer in English." in build_chat(EN)[0]["content"]


def test_build_chat_of_undetected_language_has_no_examples():
    chat = build_chat("ok!")
    assert len(chat) == 2 and "same language" in chat[0]["content"]


def test_clean_output_strips_wrappers():
    assert clean_output('<think>\n\n</think>\n\n"Oi, tudo bem?"') == "Oi, tudo bem?"
    assert clean_output("```\nOi, tudo bem?\n```") == "Oi, tudo bem?"
    assert clean_output("Here is the rewritten message:\nHi, all good?") == "Hi, all good?"
    assert clean_output("Aqui está a mensagem revisada:\n\nOi, tudo bem?") == "Oi, tudo bem?"


def test_clean_output_keeps_inner_quotes():
    assert clean_output('Ele disse "ok" ontem.') == 'Ele disse "ok" ontem.'


def test_clean_output_keeps_a_message_that_ends_with_a_colon_line():
    assert clean_output("Pessoal, seguem os itens:\n- deploy\n- migration") == \
        "Pessoal, seguem os itens:\n- deploy\n- migration"


def test_reapply_whitespace_keeps_trailing_newline():
    assert reapply_whitespace("oi tudo bem\n", "Oi, tudo bem?") == "Oi, tudo bem?\n"


def test_reapply_whitespace_keeps_leading_indent():
    assert reapply_whitespace("  oi\n", "Oi!") == "  Oi!\n"


def test_max_new_tokens():
    assert max_new_tokens(100) == 264
