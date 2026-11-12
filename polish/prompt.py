"""What Polish asks the model, and how its answer is cleaned up.

Standard library only, so it can be unit-tested without OpenVINO.
"""
import re

from polish.factcheck import detect_language

SYSTEM = """You are a UX writer who polishes short workplace messages (team chat or a quick email) before they are sent.

Language: answer in the language the message is written in. A Portuguese message gets a Portuguese answer even when it is short or full of English tech terms (deploy, staging, PR). Never translate.

Goal: the reader understands the message at first glance.
- Fix spelling, accents, capital letters, grammar and punctuation. Expand chat abbreviations (hj, tbm, vc, pq, ta, pra, q, u, pls).
- Make sentences clear: one idea per sentence, and put the request or the key point where it stands out. Use a short list only when the message has several separate items.
- Keep the author's voice: casual stays casual. In Portuguese write natural Brazilian Portuguese ("foi movida", "lembrando que"), never stiff forms ("lembremos", "moveu-se").

Hard rules:
- Keep EVERY piece of information: names, days (today/tomorrow/Monday), times, numbers, versions, links, file names, requests and deadlines, exactly as written.
- Keep every word that changes the meaning: again/de novo, still/ainda, only/só, also/também, not/não, yet.
- Keep who does what: "consigo"/"I can" stays the author, it never becomes "pode"/"you can".
- Do not add facts, greetings, sign-offs or emojis.
- Output only the rewritten message. No preamble, quotes or notes."""

# Few-shot pairs (before, after) per language; only the message's language is
# shown, because examples in another language pull the model into translating.
EXAMPLES: dict[str, list[tuple[str, str]]] = {
    "en": [
        ("hey the tests are failing again on main since yesterday, not sure why, can u take a look pls",
         "Hey, the tests have been failing again on main since yesterday, and I'm not sure why. "
         "Can you take a look, please?"),
        ("i can review it only tomorrow, its not urgent right?",
         "I can only review it tomorrow. It's not urgent, right?"),
    ],
    "pt": [
        ("lembrando q a daily de amanha foi movida pras 10h, vc consegue avisar o time? o build quebrou de novo hj",
         "Lembrando que a daily de amanhã foi movida para as 10h. Você consegue avisar o time? "
         "O build quebrou de novo hoje."),
        ("nao precisa subir o PR hj, consigo revisar so amanha",
         "Não precisa subir o PR hoje. Só consigo revisar amanhã."),
    ],
}
LANGUAGE_NAMES = {"en": "English", "pt": "Portuguese"}

_THINK = re.compile(r"<think>.*?</think>", re.S)
_PREAMBLE = re.compile(r"^(here'?s|here is|aqui est[aá]|segue)\b.{0,80}:\s*$", re.I)
_WRAPPERS = [("```", "```"), ('"', '"'), ("“", "”"), ("'", "'")]


def build_chat(text: str) -> list[dict]:
    lang = detect_language(text)
    if lang:
        name = LANGUAGE_NAMES[lang]
        note = f"This message is in {name}. Answer in {name}."
    else:
        note = "Answer in the same language as the message."
    chat = [{"role": "system", "content": f"{SYSTEM}\n\n{note}"}]
    for before, after in EXAMPLES.get(lang, []):
        chat += [{"role": "user", "content": before}, {"role": "assistant", "content": after}]
    chat.append({"role": "user", "content": text})
    return chat


def clean_output(raw: str) -> str:
    text = _THINK.sub("", raw).strip()
    first, _, rest = text.partition("\n")
    if rest and _PREAMBLE.match(first):
        text = rest.strip()
    for left, right in _WRAPPERS:
        inner = text[len(left):-len(right)] if len(text) > len(left) + len(right) else ""
        if text.startswith(left) and text.endswith(right) and left not in inner and right not in inner:
            text = inner.strip()
            break
    return text


def reapply_whitespace(original: str, rewritten: str) -> str:
    """Keep the selection's leading and trailing whitespace (a triple-click grabs the newline)."""
    lead = original[:len(original) - len(original.lstrip())]
    trail = original[len(original.rstrip()):]
    return lead + rewritten.strip() + trail


def max_new_tokens(input_tokens: int) -> int:
    return 2 * input_tokens + 64
