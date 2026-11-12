"""Deterministic fact check: does a rewrite keep every fact of the original?

No model involved. `check` lists what the rewrite lost or changed; an empty list
means it is safe to use. It cannot catch every dropped word (that is the
prompt's job), only the facts below:

  number    digit groups (times, dates, versions, IDs)
  verbatim  URLs, emails, @mentions, #channels, `code`, emoji
  day       today/tomorrow/weekday words, which must match exactly
  negation  não/not/never..., which must not decrease
  keyword   again/de novo/still/ainda/only/só/yet/also..., which must not decrease
  name      capitalised words that are not sentence-initial
  language  the rewrite must be in the original's language
"""
import re
import unicodedata
from collections import Counter

DAYS = frozenset(
    "hoje amanha ontem segunda terca quarta quinta sexta sabado domingo "
    "today tomorrow tonight yesterday monday tuesday wednesday thursday friday saturday sunday".split())

# Chat spellings of day words: "hj" rewritten as "hoje" is the same day.
DAY_ABBREVIATIONS = {"hj": "hoje", "hje": "hoje", "amn": "amanha", "amnh": "amanha",
                     "tmrw": "tomorrow", "tmr": "tomorrow", "2morrow": "tomorrow", "tdy": "today",
                     "2day": "today", "yday": "yesterday", "seg": "segunda", "sex": "sexta"}

NEGATIONS = {
    "pt": frozenset("nao nunca nem jamais ninguem".split()),
    "en": frozenset("not never no nobody nothing cannot".split()),
}

# Words that change the meaning when dropped ("failed again" vs "failed"). Each
# group lists equivalent spellings; the rewrite must have at least as many.
KEYWORDS = {
    "pt": {"de novo": ("de novo", "novamente", "outra vez"), "ainda": ("ainda",),
           "só": ("so", "somente", "apenas"), "também": ("tambem", "tbm", "tb")},
    "en": {"again": ("again", "once more"), "still": ("still",), "only": ("only",),
           "yet": ("yet",), "also": ("also", "as well")},
}

STOPWORDS = {
    "pt": frozenset(
        "de que e o os as um uma para pra com nao se por mais como mas foi ao do da dos das no na em "
        "voce vc isso esta ta tem eu consegue ja tambem tbm aqui entao porque pq".split()),
    "en": frozenset(
        "the and to of is it you that in for on with this be can we are have not if but so do at "
        "me my i will just please thanks was".split()),
}

_WORD = re.compile(r"\w+")
_VERBATIM = re.compile(
    r"https?://\S+?(?=[.,;:!?)\]]*(?:\s|$))"  # URL without trailing punctuation
    r"|[\w.+-]+@[\w-]+\.[\w.-]+"              # email
    r"|(?<![\w@])@\w+"                         # @mention
    r"|(?<![\w&])#[\w-]+"                      # #channel
    r"|`[^`]+`")                               # code span


def normalize(s: str) -> str:
    """Casefold and strip accents (João → joao)."""
    decomposed = unicodedata.normalize("NFKD", s.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _words(s: str) -> list[str]:
    return _WORD.findall(normalize(s))


def detect_language(text: str) -> str | None:
    words = _words(text)
    hits = {lang: sum(w in sw for w in words) for lang, sw in STOPWORDS.items()}
    (best, top), (_, other) = sorted(hits.items(), key=lambda kv: -kv[1])
    if top < 3 or top < 1.5 * other:
        return None
    return best


def _days(s: str) -> list[str]:
    words = (DAY_ABBREVIATIONS.get(w, w) for w in _words(s))
    return [w for w in words if w in DAYS]


def _verbatim(s: str) -> list[str]:
    tokens = _VERBATIM.findall(s)
    tokens += [c for c in s if unicodedata.category(c) == "So"]
    return tokens


def _negations(s: str, lang: str | None) -> int:
    words = NEGATIONS.get(lang) if lang else NEGATIONS["pt"] | (NEGATIONS["en"] - {"no"})
    norm = normalize(s).replace("’", "'")
    return sum(w in words for w in _WORD.findall(norm)) + len(re.findall(r"n't\b", norm))


def _keyword_groups(lang: str | None) -> dict[str, tuple[str, ...]]:
    if lang:
        return KEYWORDS[lang]
    groups = KEYWORDS["pt"] | KEYWORDS["en"]
    groups["só"] = ("somente", "apenas")  # bare "so" is also English
    return groups


def _count_phrases(norm: str, phrases: tuple[str, ...]) -> int:
    return sum(len(re.findall(rf"\b{re.escape(p)}\b", norm)) for p in phrases)


def _names(s: str) -> list[str]:
    names = []
    for m in re.finditer(r"\w+", s):
        word = m.group()
        if not word[0].isupper() or word == "I":
            continue
        before = s[:m.start()].rstrip(" \t\"'(“")
        if not before or before[-1] in ".!?:\n":
            continue  # sentence-initial: capitalised for grammar, not a name
        names.append(normalize(word))
    return names


def check(original: str, rewritten: str) -> list[str]:
    missing: list[str] = []
    norm_rw = normalize(rewritten)

    have = Counter(re.findall(r"\d+", norm_rw))
    for n, count in Counter(re.findall(r"\d+", normalize(original))).items():
        if have[n] < count:
            missing.append(f"number:{n}")

    for token in dict.fromkeys(_verbatim(original)):
        if token not in rewritten:
            missing.append(f"verbatim:{token}")

    days_orig = Counter(w for w in _days(original))
    days_rw = Counter(w for w in _days(rewritten))
    for day in sorted(days_orig.keys() | days_rw.keys()):
        if days_orig[day] > days_rw[day]:
            missing.append(f"day:{day}")
        elif days_rw[day] > days_orig[day]:
            missing.append(f"day:+{day}")

    lang = detect_language(original)
    lost = _negations(original, lang) - _negations(rewritten, lang)
    if lost > 0:
        missing.append(f"negation:{lost}")

    norm_orig = normalize(original)
    for label, phrases in _keyword_groups(lang).items():
        if _count_phrases(norm_orig, phrases) > _count_phrases(norm_rw, phrases):
            missing.append(f"keyword:{label}")

    for name in dict.fromkeys(_names(original)):
        if not re.search(rf"\b{re.escape(name)}\b", norm_rw):
            missing.append(f"name:{name}")

    lang_rw = detect_language(rewritten)
    if lang and lang_rw and lang != lang_rw:
        missing.append(f"language:{lang}>{lang_rw}")

    return missing
