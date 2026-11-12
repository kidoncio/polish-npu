"""What Polish asks the model, and how its answer is cleaned up.

Standard library only, so it can be unit-tested without OpenVINO.
"""
import re

SYSTEM = """You are a UX writer who polishes short workplace messages (team chat or a quick email) before they are sent.

Goal: the reader understands the message at first glance.
- Fix spelling, accents, grammar and punctuation. Expand chat abbreviations (hj, tbm, vc, pq, ta, pra).
- Make sentences clear: one idea per sentence, put the request or the key point where it stands out, use a short list only if the message has several separate items.
- Keep the author's tone and register: a casual note stays casual, never stiff or corporate.

Hard rules:
- Same language as the original. Never translate.
- Keep EVERY piece of information: names, dates and days (today/tomorrow/Monday), times, numbers, versions, links, file names, requests and deadlines. Never change, guess, summarize or drop any of them.
- Do not add facts, greetings, sign-offs or emojis the author did not write.
- Output only the rewritten message. No preamble, quotes or notes."""

# Few-shot pairs (before, after). They target the failures seen in the spike:
# dropped words ("de novo", "again"), missing accents and capitals, stiff Portuguese.
EXAMPLES: list[tuple[str, str]] = [
    ("vc viu q o build quebrou de novo? acho q é a lib nova, consegue olhar hj ou amanha cedo",
     "Você viu que o build quebrou de novo? Acho que é a lib nova. Consegue olhar hoje ou amanhã cedo?"),
    ("hey the tests are failing again on main since yesterday, not sure why, can u take a look pls",
     "Hey, the tests have been failing again on main since yesterday and I'm not sure why. "
     "Can you take a look, please?"),
]

_THINK = re.compile(r"<think>.*?</think>", re.S)
_PREAMBLE = re.compile(r"^(here'?s|here is|aqui est[aá]|segue)\b.{0,80}:\s*$", re.I)
_WRAPPERS = [("```", "```"), ('"', '"'), ("“", "”"), ("'", "'")]


def build_chat(text: str) -> list[dict]:
    chat = [{"role": "system", "content": SYSTEM}]
    for before, after in EXAMPLES:
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
