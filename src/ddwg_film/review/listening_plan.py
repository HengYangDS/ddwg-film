"""Derive the pronunciation listening plan of both editions.

The plan lists every dictionary target occurrence of the voice-performance contract
and every current English heteronym with the part of speech its clause gives it, so
a reviewer and the later human listening check each one in context. A heteronym
occurrence takes the reading GRAMMAR records for it, or the derivation refuses, so an
edit that moves or adds one is re-read before the next review. A refusal raises
`ReviewError`, which the command reports.

Usage: python -m ddwg_film.review.listening_plan --out <file>
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import ddwg_film.repository as repository
import ddwg_film.sources as sources
from ddwg_film.production import CODES, Edition
from ddwg_film.review import ReviewError

if TYPE_CHECKING:
    from collections.abc import Iterator

BASIS = (
    "Analyst-stated CMU-convention reading; not read from the pinned dictionary; listening confirms"
)
READING = "See target dictionary reading and admissible lexical-stress variants"
PLAN_AUTHORITY = (
    "Derived review aid; the contract and the recordings remain the owners. Listening decides."
)


def arpabet(phones: str, primary: int, secondary=(), weak=()) -> dict:
    """An analyst-stated reading in the contract's lexical-stress shape."""
    values = phones.split()
    return {
        "arpabet": values,
        "syllable_count": sum(phone[-1].isdigit() for phone in values),
        "primary_syllable": primary,
        "secondary_syllables": list(secondary),
        "weak_syllables": list(weak),
        "basis": BASIS,
    }


# Current English heteronyms whose reading depends on part of speech or tense.
HETERONYMS = {
    "lead": {"noun": arpabet("L IY1 D", 1), "verb": arpabet("L IY1 D", 1)},
    "leads": {"noun": arpabet("L IY1 D Z", 1), "verb": arpabet("L IY1 D Z", 1)},
    "read": {"present": arpabet("R IY1 D", 1)},
    "reads": {"present": arpabet("R IY1 D Z", 1)},
    "close": {"verb": arpabet("K L OW1 Z", 1)},
    "present": {
        "adjective": arpabet("P R EH1 Z AH0 N T", 1, weak=[2]),
        "verb": arpabet("P R IY0 Z EH1 N T", 2, weak=[1]),
    },
    "permit": {"verb": arpabet("P ER0 M IH1 T", 2, weak=[1])},
    "permits": {"verb": arpabet("P ER0 M IH1 T S", 2, weak=[1])},
    "conflict": {
        "noun": arpabet("K AA1 N F L IH0 K T", 1, weak=[2]),
        "verb": arpabet("K AH0 N F L IH1 K T", 2, weak=[1]),
    },
    "conflicts": {"noun": arpabet("K AA1 N F L IH0 K T S", 1, weak=[2])},
    "subject": {"noun": arpabet("S AH1 B JH IH0 K T", 1, weak=[2])},
    "delegate": {"verb": arpabet("D EH1 L AH0 G EY2 T", 1, secondary=[3], weak=[2])},
    "delegated": {"verb": arpabet("D EH1 L AH0 G EY2 T IH0 D", 1, secondary=[3], weak=[2, 4])},
    "separate": {"adjective": arpabet("S EH1 P ER0 IH0 T", 1, weak=[2, 3])},
    "separates": {"verb": arpabet("S EH1 P ER0 EY2 T S", 1, secondary=[3], weak=[2])},
    "produce": {"verb": arpabet("P R AH0 D UW1 S", 2, weak=[1])},
    "duplicates": {"verb": arpabet("D UW1 P L AH0 K EY2 T S", 1, secondary=[3], weak=[2])},
    "digest": {"noun": arpabet("D AY1 JH EH0 S T", 1, weak=[2])},
    "update": {"noun": arpabet("AH1 P D EY2 T", 1, secondary=[2])},
    "coordinates": {"verb": arpabet("K OW0 AO1 R D AH0 N EY2 T S", 2, secondary=[4], weak=[1, 3])},
    "recording": {"verb": arpabet("R AH0 K AO1 R D IH0 NG", 2, weak=[1, 3])},
    "contracts": {"noun": arpabet("K AA1 N T R AE2 K T S", 1, secondary=[2])},
}
# Variants that the dictionary-sourced homograph targets lack for the current text.
EXTRA_VARIANTS = {"uses": {"verb": arpabet("Y UW1 Z IH0 Z", 1, weak=[2])}}
# The part of speech of each heteronym occurrence, read from its clause and keyed by
# "<segment>:<offset>" in the English segment text. A script edit that moves or adds
# an occurrence makes the plan refuse until its entry here is recorded again.
GRAMMAR = {
    "lead": {
        "11:1139": "noun",
        "13:917": "noun",
        "14:680": "noun",
        "20:35": "noun",
        "20:131": "noun",
        "25:658": "verb",
        "29:841": "noun",
    },
    "leads": {"23:242": "verb"},
    "reads": {"18:674": "present", "21:597": "present"},
    "close": {"04:843": "verb"},
    "present": {"05:393": "adjective", "22:606": "verb", "23:271": "adjective"},
    "permit": {"13:851": "verb"},
    "permits": {"12:857": "verb", "20:113": "verb"},
    "conflict": {"03:970": "noun", "13:502": "noun", "22:95": "verb", "29:197": "verb"},
    "conflicts": {"29:96": "noun"},
    "subject": {
        "03:698": "noun",
        "04:175": "noun",
        "05:360": "noun",
        "05:596": "noun",
        "05:828": "noun",
        "06:590": "noun",
        "14:658": "noun",
        "16:325": "noun",
        "17:404": "noun",
        "18:177": "noun",
        "23:636": "noun",
        "25:462": "noun",
        "25:794": "noun",
        "26:789": "noun",
    },
    "delegate": {"03:57": "verb", "19:8": "verb", "19:221": "verb"},
    "delegated": {"19:140": "verb"},
    "separate": {"07:251": "adjective"},
    "separates": {"07:551": "verb", "07:718": "verb"},
    "produce": {"02:391": "verb", "24:16": "verb"},
    "duplicates": {"26:807": "verb"},
    "update": {"23:235": "noun"},
    "coordinates": {"13:922": "verb"},
    "recording": {"29:1103": "verb"},
    "contracts": {"03:478": "noun"},
    "record": {
        "03:1011": "noun",
        "04:1010": "noun",
        "15:724": "verb",
        "15:776": "noun",
        "21:979": "noun",
        "27:783": "noun",
        "29:1172": "noun",
    },
    "records": {"03:527": "noun", "03:640": "noun"},
    "use": {
        "01:67": "verb",
        "05:276": "verb",
        "09:101": "noun",
        "11:1101": "noun",
        "12:261": "noun",
        "12:351": "noun",
        "12:392": "noun",
        "12:463": "noun",
        "12:513": "noun",
        "12:668": "noun",
        "12:842": "noun",
        "12:877": "noun",
        "12:962": "noun",
        "13:782": "noun",
        "13:1106": "noun",
        "14:1117": "noun",
        "16:510": "noun",
        "25:895": "noun",
        "29:377": "verb",
        "29:681": "noun",
        "30:168": "noun",
    },
    "uses": {"18:649": "verb"},
    "project": {"27:430": "noun"},
}


def occurrences(term: str, text: str, code: str) -> Iterator[tuple[int, int]]:
    """Spans of a term in a segment's text: substrings in Chinese, words in English."""
    if code == "zh":
        start = text.find(term)
        while start >= 0:
            yield start, start + len(term)
            start = text.find(term, start + 1)
        return
    flags = 0 if term.isupper() else re.IGNORECASE
    for match in re.finditer(rf"\b{re.escape(term)}\b", text, flags):
        yield match.start(), match.end()


# Chinese words whose reading depends on context and that the dictionary targets do not
# cover, each with the reading its sentence gives it.
MANDARIN_READINGS = {
    "偏好": "piānhào",
    "补一次数": "bǔ yí cì shù",
    "降级": "jiàngjí",
    "偏差": "piānchā",
    "沉没": "chénmò",
    "漂亮": "piàoliang",
    "漂移": "piāoyí",
    "重新": "chóngxīn",
    "塞进": "sāijìn",
    "阻塞": "zǔsè",
    "不了": "bùliǎo",
    "标识": "biāozhì or biāoshí (both in current use; either is accepted)",
    "处置": "chǔzhì",
    "处理": "chǔlǐ",
    "调用": "diàoyòng",
    "调查": "diàochá",
    "相应": "xiāngyìng",
    "长期": "chángqī",
    "更长": "gèng cháng",
    "重大": "zhòngdà",
    "模型": "móxíng",
    "模拟": "mónǐ",
    "模式": "móshì",
    "模板": "múbǎn",
    "成长": "chéngzhǎng",
    "差距": "chājù",
    "校准": "jiàozhǔn",
    "暴露": "bàolù",
    "了解": "liǎojiě",
    "懂行": "dǒngháng",
    "行为": "xíngwéi",
    "划清": "huàqīng",
    "划不出": "huà bu chū",
    "一字不差": "yí zì bú chà",
    "差异": "chāyì",
    "角色": "juésè",
    "目的": "mùdì",
    "得不偿失": "dé bù cháng shī",
    "要求": "yāoqiú",
    "变更": "biàngēng",
    "充分": "chōngfèn",
    "充当": "chōngdāng",
    "答应": "dāying",
    "钻空子": "zuān kòngzi",
    "格调": "gédiào",
    "该尽的": "gāi jìn de",
    "应对": "yìngduì",
    "假定": "jiǎdìng",
    "强制性": "qiángzhìxìng",
    "供应商": "gōngyìngshāng",
    "运行": "yùnxíng",
}
MANDARIN_BASIS = (
    "Analyst-stated Hanyu Pinyin reading in context; not read from the pinned "
    "dictionary; listening confirms"
)


def analyst_contract(contract: dict) -> dict:
    """The pronunciation contract with the analyst-stated readings and variants."""
    chinese = contract["languages"]["Chinese"]
    if not any(source["id"] == "analyst-mandarin" for source in contract["sources"]):
        contract["sources"].append({"id": "analyst-mandarin", "qualification": MANDARIN_BASIS})
    known = {target["term"] for target in chinese["targets"]}
    for term, reading in MANDARIN_READINGS.items():
        if term not in known:
            chinese["targets"].append(
                {
                    "term": term,
                    "kind": "contextual-mandarin-word",
                    "target_reading": reading,
                    "source": "analyst-mandarin",
                    "status": "planned-not-listened",
                }
            )
    english = contract["languages"]["English"]
    known = {target["term"] for target in english["targets"]}
    if not any(source["id"] == "analyst-inference" for source in contract["sources"]):
        contract["sources"].append({"id": "analyst-inference", "qualification": BASIS})
    for term, variants in HETERONYMS.items():
        if term not in known:
            english["targets"].append(
                {
                    "term": term,
                    "kind": "contextual-homograph",
                    "lexical_stress": variants,
                    "source": "analyst-inference",
                }
            )
    # A variant the target already holds keeps its own source; only an added one is the
    # analyst's inference.
    for target in english["targets"]:
        for variant, reading in EXTRA_VARIANTS.get(target["term"], {}).items():
            if variant not in target["lexical_stress"]:
                target["lexical_stress"][variant] = reading
                target["variant_sources"] = {
                    **target.get("variant_sources", {}),
                    variant: "analyst-inference",
                }
    return contract


def target_entries(code: str, target: dict, segments: list[dict]) -> list[dict]:
    """Every occurrence of one pronunciation target in a script, with its clause.

    A heteronym's lexical stress maps each part of speech to a reading; an occurrence
    takes the reading of the part of speech GRAMMAR records for it, or is refused.
    """
    term, stress = target["term"], target.get("lexical_stress", {})
    heteronym = (
        isinstance(stress, dict)
        and bool(stress)
        and "arpabet" not in stress
        and "basis" not in stress
    )
    entries = []
    for segment in segments:
        text, offset, groups = segment["text"], 0, []
        for group in segment["utterance_groups"]:
            groups.append((offset, offset + len(group), group))
            offset += len(group)
        for start, end in occurrences(term, text, code):
            clause = next((group for a, b, group in groups if a <= start < b), None)
            if clause is None:
                msg = f"{segment['id']}: {term} at {start} lies outside every thought"
                raise ReviewError(msg)
            entry = {
                "locale": code,
                "section": segment["id"],
                "display_span": [start, end],
                "display_word": text[start:end],
                "target_owner_term": term,
                "grammar": target["kind"],
                "clause": clause,
            }
            if code == "zh":
                entry |= {
                    "target_reading": target["target_reading"],
                    "target_stress": {},
                }
            else:
                reading = stress
                if heteronym:
                    key = f"{segment['id']}:{start}"
                    entry["grammar"] = GRAMMAR.get(term, {}).get(key)
                    if entry["grammar"] not in stress:
                        msg = f"{term} at {key}: record its part of speech before rebinding"
                        raise ReviewError(msg)
                    reading = stress[entry["grammar"]]
                entry |= {"target_reading": READING, "target_stress": reading}
            entries.append(entry | {"waveform": None, "status": "planned-not-listened"})
    return entries


def listening_plan(out: Path) -> dict:
    """Derive the pronunciation listening plan from the contract and current scripts.

    content/voice-performance.json stays unchanged: its hash is part of every
    recording's fingerprint, and the narrator consumes only its normalization (none).
    The derived, planned-not-listened plan for the human listener lists every
    dictionary-sourced target, the context-dependent Chinese readings the targets do
    not cover, the current English heteronyms with analyst-stated
    CMU-convention readings, and each occurrence in the current spoken text with its
    clause and, for a heteronym, the part of speech read from that clause (GRAMMAR),
    bound to the current script, cast and reference hashes. An occurrence without a
    recorded part of speech, or a recorded one that names no current occurrence, is
    refused, so a script edit cannot silently inherit a stale reading.
    """
    contract_path = repository.ROOT / "content/voice-performance.json"
    manifest = repository.ROOT / sources.MANIFEST
    contract = analyst_contract(repository.read(contract_path)["pronunciation"])
    entries, bindings = [], []
    for code in CODES:
        edition = Edition(code)
        language, script_path, cast_path = edition.language, edition.script, edition.cast
        script, cast = repository.read(script_path), repository.read(cast_path)
        bindings.append(
            {
                "locale": code,
                "path": script_path,
                "sha256": repository.sha(script_path),
                "source_manifest": {
                    "path": sources.MANIFEST,
                    "sha256": repository.sha(manifest),
                },
                "cast": {"path": cast_path, "sha256": repository.sha(cast_path)},
                "selected_reference": {
                    "path": cast["reference_audio"],
                    "sha256": cast["reference_sha256"],
                    "transcript_sha256": cast["reference_text_sha256"],
                },
                "status": "planned-not-listened",
            }
        )
        for target in contract["languages"][language]["targets"]:
            entries += target_entries(code, target, script["segments"])
    current = {
        (entry["target_owner_term"], f"{entry['section']}:{entry['display_span'][0]}")
        for entry in entries
        if entry["locale"] == "en"
    }
    stale = {
        term: sorted(key for key in keys if (term, key) not in current)
        for term, keys in GRAMMAR.items()
    }
    stale = {term: keys for term, keys in stale.items() if keys}
    if stale:
        msg = f"recorded parts of speech name no current occurrence: {stale}"
        raise ReviewError(msg)
    repository.write(
        out,
        {
            "status": "planned-not-listened",
            "derived_from": {
                "path": "content/voice-performance.json",
                "sha256": repository.sha(contract_path),
            },
            "authority": PLAN_AUTHORITY,
            "sources": contract["sources"],
            "control_boundary": contract["control_boundary"],
            "acceptance": contract["acceptance"],
            "languages": contract["languages"],
            "script_bindings": bindings,
            "occurrence_plan": {"count": len(entries), "entries": entries},
        },
    )
    return {
        "output": repository.relative(out),
        "occurrences": {code: sum(entry["locale"] == code for entry in entries) for code in CODES},
        "english_targets": len(contract["languages"]["English"]["targets"]),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, metavar="FILE")
    options = parser.parse_args(argv)
    try:
        result = listening_plan(options.out.resolve())
    except ReviewError as error:
        msg = f"listening plan: {error}"
        raise SystemExit(msg) from None
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
