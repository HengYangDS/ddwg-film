"""Set an English passage as caption lines that break at grammatical boundaries.

Each sentence, and each long independent clause, is kept together, and its lines take the
cheapest breaks: after a phrase mark or before a clause, phrase or predicate, never inside a
fixed term or after a word that binds to what follows, at a comfortable line length.
"""

from __future__ import annotations

import re

from filmkit.captions import CaptionError
from filmkit.narration.spoken_units import (
    CLOSING_MARKS,
    PHRASE_BREAKS,
    SEMICOLONS,
    SENTENCE_ENDS,
)
from filmkit.specification import CAPTION_LIMITS

_ENDS, _CLOSERS, _SEMICOLONS = (
    re.escape(marks) for marks in (SENTENCE_ENDS, CLOSING_MARKS, SEMICOLONS)
)
# Abbreviations such as "e.g." and decimal points do not end a sentence.
_PROTECTED_DOTS = re.compile(r"\b(?:[A-Za-z]\.){2,}|(?<=\w)\.(?=\w)")
# A sentence runs through its end marks, the closing marks after them and the spaces after
# those; the passage's last sentence may have no end mark.
_SENTENCE = re.compile(rf"[^{_ENDS}]*[{_ENDS}]+(?:[{_CLOSERS}]+[{_ENDS}]*)*[ \t]*|[^{_ENDS}]+$")
_CLAUSE = re.compile(rf"[^{_SEMICOLONS}]*[{_SEMICOLONS}][{_CLOSERS}]*[ \t]*|[^{_SEMICOLONS}]+$")
# A clause of fewer than 16 characters or three words introduces its continuation and stays
# with it.
INTRODUCTION_CHARACTERS = 16
INTRODUCTION_WORDS = 3


def _long_sentence_clauses(sentence: str) -> list[str]:
    """Divide a sentence at its semicolons; a short introductory instruction stays whole."""
    clauses, buffer = [], ""
    for clause in _CLAUSE.findall(sentence):
        buffer += clause
        if (
            len(buffer.rstrip()) >= INTRODUCTION_CHARACTERS
            and len(buffer.split()) >= INTRODUCTION_WORDS
        ):
            clauses.append(buffer)
            buffer = ""
    if buffer:
        clauses.append(buffer)
    return clauses


def english_caption_sentences(text: str, limit: int = CAPTION_LIMITS["en"]) -> list[str]:
    """Keep complete sentences and long independent clauses together.

    A sentence longer than the caption limit divides at its semicolons. No English caption
    crosses the end of one of these units; they are not the narration's thought groups.
    """
    protected = _PROTECTED_DOTS.sub(lambda match: match[0].replace(".", "\0"), text)
    sentences = [text[match.start() : match.end()] for match in _SENTENCE.finditer(protected)]
    if "".join(sentences) != text:
        msg = "English caption sentences must preserve the exact text"
        raise CaptionError(msg)
    groups = []
    for sentence in sentences:
        groups.extend([sentence] if len(sentence) <= limit else _long_sentence_clauses(sentence))
    if "".join(groups) != text:
        msg = "English thought groups must preserve the exact text"
        raise CaptionError(msg)
    return groups


CLAUSE_STARTS = frozenset(
    {
        "if",
        "when",
        "while",
        "unless",
        "until",
        "because",
        "although",
        "though",
        "whereas",
        "since",
        "once",
        "whether",
    }
)
# Words that bind to what follows: a line never ends on one unless punctuation closes its
# phrase there.
GLUE = CLAUSE_STARTS | frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "nor",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "from",
        "with",
        "without",
        "through",
        "per",
        "as",
        "than",
        "into",
        "across",
        "between",
        "against",
        "during",
        "about",
        "before",
        "after",
        "within",
        "its",
        "their",
        "our",
        "your",
        "his",
        "her",
        "my",
        "whose",
        "this",
        "these",
        "those",
        "each",
        "every",
        "any",
        "some",
        "no",
        "such",
        "another",
        "both",
        "all",
        "either",
        "neither",
        "several",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "that",
        "which",
        "who",
        "whom",
        "where",
        "why",
        "how",
        "what",
        "we",
        "they",
        "you",
        "he",
        "she",
        "i",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "can",
        "could",
        "may",
        "might",
        "must",
        "should",
        "will",
        "would",
        "shall",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "not",
        "cannot",
        "never",
        "only",
        "also",
        "even",
        "just",
        "still",
        "already",
    }
)
QUALIFIED_STARTS = frozenset(
    {
        ("only", "when"),
        ("only", "if"),
        ("even", "if"),
        ("even", "when"),
        ("rather", "than"),
    }
)
CONJUNCTIONS = frozenset({"and", "or", "but", "nor"})
# Modifiers joined by these share the noun after them.
JOINERS = frozenset({"and", "or"})
PHRASE_STARTS = frozenset(
    {
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "from",
        "with",
        "without",
        "through",
        "per",
        "as",
        "than",
        "before",
        "after",
        "into",
        "across",
        "between",
        "against",
        "during",
        "about",
        "or",
        "but",
        "nor",
    }
)
PREDICATE_STARTS = frozenset(
    {
        "can",
        "could",
        "may",
        "might",
        "must",
        "should",
        "will",
        "would",
        "shall",
        "is",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
    }
)
# A term that reads as one name stays on one line, as do a verb and the object
# pronoun or noun phrase it takes, and a modifier and the noun it qualifies.
FIXED_TERMS = tuple(
    tuple(term.split())
    for term in (
        "source of truth",
        "sources of truth",
        "decision owner",
        "task lead",
        "release owner",
        "work cycle",
        "permission or compliance",
        "resource limits",
        "publication time",
        "price snapshots",
        "goes back to the member",
        "make up for",
        "fabricated selectively hidden or unverified facts",
        "agent output",
        "standing in for",
        "fact authorization or responsibility",
        "data department work guidelines",
        "operational delivery",
        "the problem scope or completion condition",
    )
)
OBJECT_PRONOUNS = frozenset({"it", "them", "him", "her", "us", "me"})
MODIFIER_ENDINGS = ("ible", "able", "ive", "ous", "ful", "ical", "ed")
DETERMINERS = frozenset(
    {
        "a",
        "an",
        "the",
        "this",
        "these",
        "those",
        "its",
        "their",
        "our",
        "your",
        "his",
        "her",
        "my",
        "each",
        "every",
        "any",
        "some",
        "no",
        "such",
        "another",
        "both",
        "all",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
    }
)
# A verb or adjective keeps the particle its sense needs ("lead to", "rests on"),
# and an adjective phrase after its noun ("the person closest to the facts")
# stays with that noun.
BOUND_PAIRS = frozenset(
    (verb, particle)
    for verbs, particle in (
        ("lead leads led need needs closest", "to"),
        ("rest rests depend depends rely relies", "on"),
        ("belong belongs", "with"),
        ("presented treated counted described shown reported recorded regarded", "as"),
    )
    for verb in verbs.split()
)
# A verb of instruction keeps the infinitive it gives its object ("telling an
# Agent to ...").
INSTRUCTIONS = frozenset(
    {
        "tell",
        "tells",
        "telling",
        "told",
        "ask",
        "asks",
        "asking",
        "asked",
        "allow",
        "allows",
        "allowing",
        "allowed",
        "require",
        "requires",
        "requiring",
        "required",
        "expect",
        "expects",
        "expecting",
        "expected",
        "instruct",
        "instructs",
        "instructing",
        "instructed",
        "permit",
        "permits",
        "permitting",
        "permitted",
    }
)
POSTNOMINAL = frozenset({("closest", "to")})
# Punctuation that closes a phrase where a line may end.
_CLOSES_PHRASE = PHRASE_BREAKS + SENTENCE_ENDS


def _participle(word: str) -> bool:
    return len(word) > 4 and word.endswith("ed") and not word.endswith("eed")


def _possessive(word: str) -> bool:
    return bool(re.search(r"['’]s$", word))


def _word(token: str) -> str:
    """A token's word: lowercased, without the punctuation around it."""
    return re.sub(r"^[^\w]+|[^\w]+$", "", token.strip()).lower()


def _break_strength(words: list[str], last: int, tail_end: str) -> int:
    """How strongly the text breaks before word last; a lower strength is a better line end.

    A phrase mark breaks most strongly, then the opening of a clause, of a phrase and of a
    predicate; any other break falls inside a phrase.
    """
    following = words[last]
    if tail_end in PHRASE_BREAKS:
        return 2
    if (
        following in CLAUSE_STARTS
        or tuple(words[last : last + 2]) in QUALIFIED_STARTS
        or (
            following in CONJUNCTIONS
            and last + 1 < len(words)
            and words[last + 1] in PREDICATE_STARTS
        )
    ):
        return 3
    if following in PHRASE_STARTS or (
        # A participle after its noun opens a phrase of its own
        # ("facts presented as established").
        _participle(following) and last + 1 < len(words) and words[last + 1] in PHRASE_STARTS
    ):
        return 12
    if following in PREDICATE_STARTS | {"cannot"}:
        return 24
    return 36


def _open_break_penalty(words: list[str], last: int) -> int:
    """What a break before word last costs when no punctuation closes the phrase there."""
    following, penalty = words[last], 0
    if following in OBJECT_PRONOUNS:
        penalty += 60
    elif following in DETERMINERS:
        penalty += 30
    # A modifier before "and" or "or" shares the coming noun ("technical and resource
    # limits"); before another function word it takes a complement instead ("able to").
    if words[last - 1].endswith(MODIFIER_ENDINGS) and (
        following in JOINERS or following not in GLUE
    ):
        penalty += 40
    # Modifiers joined by "and" or "or" after a determiner or a possessive share the noun
    # after them ("the vendor's earlier and revised price snapshots").
    if (
        following in JOINERS
        and 2 <= last < len(words) - 2
        and words[last + 1].endswith(MODIFIER_ENDINGS)
        and words[last + 2] not in GLUE
        and (words[last - 2] in DETERMINERS or _possessive(words[last - 2]))
    ):
        penalty += 40
    if (words[last - 1], following) in BOUND_PAIRS:
        penalty += 60
    if following == "to" and INSTRUCTIONS & set(words[max(0, last - 3) : last]):
        penalty += 30
    if tuple(words[last : last + 2]) in POSTNOMINAL:
        penalty += 30
    return penalty


def _break_cost(tokens: list[str], words: list[str], last: int) -> int:
    """What a line that ends before token last costs for its break, wherever it starts."""
    tail_end = tokens[last - 1].rstrip()[-1]
    cost = 0
    if last < len(tokens):
        cost = _break_strength(words, last, tail_end)
        if tail_end not in _CLOSES_PHRASE:
            cost += _open_break_penalty(words, last)
        if any(
            tuple(words[last - offset : last - offset + len(term)]) == term
            for term in FIXED_TERMS
            for offset in range(1, len(term))
        ):
            cost += 90
        # A function word closing its own phrase ("delegate to:") stays with that phrase
        # rather than opening the next line.
        if words[last] in GLUE and tokens[last].rstrip()[-1] in _CLOSES_PHRASE:
            cost += 60
    # A possessive binds to the noun it names, as a determiner does.
    if (words[last - 1] in GLUE or _possessive(words[last - 1])) and tail_end not in _CLOSES_PHRASE:
        cost += 90
    return cost


def _cheapest_lines(tokens: list[str], costs: dict[int, int], limit: int) -> list[str]:
    """The cheapest lines of a sentence's tokens, each within the caption limit.

    A line costs 16, the cost of its break, 90 more when it holds fewer than three tokens or
    16 characters, and the square of its distance from 48 characters over 80. A tie keeps
    the shortest early line.
    """
    best: dict[int, tuple[float, list[str]]] = {len(tokens): (0, [])}
    for first in range(len(tokens) - 1, -1, -1):
        candidates = []
        for last in range(first + 1, len(tokens) + 1):
            cue = "".join(tokens[first:last])
            if len(cue) > limit:
                break
            if last not in best:
                continue
            tail = cue.rstrip()
            boundary = costs[last]
            short = 90 if last - first < 3 or len(tail) < 16 else 0
            cost = best[last][0] + 16 + boundary + short + (len(tail) - 48) ** 2 / 80
            candidates.append((cost, [cue, *best[last][1]]))
        if candidates:
            best[first] = min(candidates, key=lambda item: item[0])
    if 0 not in best:
        msg = "An English caption token exceeds its readable slot"
        raise CaptionError(msg)
    return best[0][1]


def english_caption_phrases(text: str, limit: int = CAPTION_LIMITS["en"]) -> list[str]:
    """Prefer grammatical boundaries over equally sized fragments of a phrase."""
    phrases: list[str] = []
    for sentence in english_caption_sentences(text, limit):
        tokens = re.findall(r"\S+\s*", sentence)
        if "".join(tokens) != sentence:
            msg = "English caption tokens must preserve exact spacing"
            raise CaptionError(msg)
        words = [_word(token) for token in tokens]
        costs = {last: _break_cost(tokens, words, last) for last in range(1, len(tokens) + 1)}
        phrases.extend(_cheapest_lines(tokens, costs, limit))
    if "".join(phrases) != text:
        msg = "English captions must retain exact narration"
        raise CaptionError(msg)
    return phrases
