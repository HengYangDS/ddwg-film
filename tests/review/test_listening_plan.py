"""Exercise the pronunciation listening plan on the current scripts and on small fixtures."""

import json
import re

import pytest

import ddwg_film.repository as repository
import ddwg_film.review.listening_plan as review_listening_plan
from ddwg_film.production import Edition
from ddwg_film.review import ReviewError


def test_the_listening_plan_derives_for_the_current_scripts(tmp_path):
    # Every heteronym occurrence of the current scripts has its part of speech recorded,
    # so a script edit cannot reach the review with a stale reading table.
    plan = review_listening_plan.listening_plan(tmp_path / "plan.json")
    assert plan["occurrences"]["zh"] > 0
    assert plan["occurrences"]["en"] > 0


def test_listening_plan_binds_each_occurrence_and_refuses_unrecorded_readings(
    root, put, monkeypatch
):
    noun, verb = (
        review_listening_plan.arpabet("Y UW1 S", 1),
        review_listening_plan.arpabet("Y UW1 Z", 1),
    )
    english = [
        {
            "term": "use",
            "kind": "contextual-homograph",
            "lexical_stress": {"noun": noun, "verb": verb},
        },
        {
            "term": "data",
            "kind": "lexical",
            "lexical_stress": review_listening_plan.arpabet("D EY1 T AH0", 1),
        },
    ]
    chinese = [{"term": "调度", "kind": "contextual-mandarin-word", "target_reading": "diàodù"}]
    contract = {
        "sources": [{"id": "cmudict"}],
        "control_boundary": "Targets are acceptance criteria.",
        "acceptance": ["Listen to each occurrence in its clause."],
        "languages": {"Chinese": {"targets": chinese}, "English": {"targets": english}},
    }
    put(root / "content/voice-performance.json", {"pronunciation": contract})
    scripts = {
        "zh": ["先看调度。", "再改调度表，重新跑。"],
        "en": ["We use data. ", "Data takes the lead."],
    }
    for code, groups in scripts.items():
        script, cast = Edition(code).script, Edition(code).cast
        segment = {"id": "01", "text": "".join(groups), "utterance_groups": groups}
        put(root / script, {"segments": [segment]})
        put(
            root / cast,
            {
                "reference_audio": f"assets/{code}.wav",
                "reference_sha256": "a" * 64,
                "reference_text_sha256": "b" * 64,
            },
        )
    put(root / "content/source-manifest.json", {"members": []})
    lead = {"noun": review_listening_plan.arpabet("L IY1 D", 1)}
    monkeypatch.setattr(review_listening_plan, "HETERONYMS", {"lead": lead})
    monkeypatch.setattr(review_listening_plan, "EXTRA_VARIANTS", {})
    monkeypatch.setattr(review_listening_plan, "MANDARIN_READINGS", {"重新": "chóngxīn"})
    monkeypatch.setattr(
        review_listening_plan, "GRAMMAR", {"use": {"01:3": "verb"}, "lead": {"01:28": "noun"}}
    )
    out = root / "plan.json"
    assert review_listening_plan.listening_plan(out) == {
        "output": "plan.json",
        "occurrences": {"zh": 3, "en": 4},
        "english_targets": 3,
    }
    plan = json.loads(out.read_text())
    entries = plan["occurrence_plan"]["entries"]
    assert [(e["locale"], e["display_span"], e["grammar"], e["clause"]) for e in entries] == [
        ("zh", [2, 4], "contextual-mandarin-word", "先看调度。"),
        ("zh", [7, 9], "contextual-mandarin-word", "再改调度表，重新跑。"),
        ("zh", [11, 13], "contextual-mandarin-word", "再改调度表，重新跑。"),
        ("en", [3, 6], "verb", "We use data. "),
        ("en", [7, 11], "lexical", "We use data. "),
        ("en", [13, 17], "lexical", "Data takes the lead."),
        ("en", [28, 32], "noun", "Data takes the lead."),
    ]
    assert entries[2]["target_reading"] == "chóngxīn"
    assert entries[3]["target_stress"] == verb
    assert entries[6]["target_stress"] == lead["noun"]
    assert {e["status"] for e in entries} == {"planned-not-listened"}
    assert plan["languages"]["English"]["targets"][-1]["source"] == "analyst-inference"
    assert {"id": "analyst-inference", "qualification": review_listening_plan.BASIS} in plan[
        "sources"
    ]
    assert plan["languages"]["Chinese"]["targets"][-1]["source"] == "analyst-mandarin"
    assert [binding["sha256"] for binding in plan["script_bindings"]] == [
        repository.sha(root / "content/film-script.json"),
        repository.sha(root / "content/en/film-script.json"),
    ]
    assert plan["derived_from"]["sha256"] == repository.sha(root / "content/voice-performance.json")

    monkeypatch.setattr(review_listening_plan, "GRAMMAR", {"lead": {"01:28": "noun"}})
    with pytest.raises(ReviewError, match="use at 01:3: record its part of speech"):
        review_listening_plan.listening_plan(out)
    monkeypatch.setattr(
        review_listening_plan,
        "GRAMMAR",
        {"use": {"01:3": "verb"}, "lead": {"01:28": "noun", "01:40": "verb"}},
    )
    stale = re.escape("no current occurrence: {'lead': ['01:40']}")
    with pytest.raises(ReviewError, match=stale):
        review_listening_plan.listening_plan(out)
    # The command reports its refusals, and lets any other fault show in full.
    with pytest.raises(SystemExit, match=f"listening plan: recorded parts of speech name {stale}"):
        review_listening_plan.main(["--out", str(out)])
    put(root / "content/voice-performance.json", "{")
    with pytest.raises(json.JSONDecodeError):
        review_listening_plan.main(["--out", str(out)])


def test_an_extra_variant_is_labelled_only_where_it_is_added(monkeypatch):
    # A dictionary reading is kept as its source states it; only an added variant is the
    # analyst's inference.
    noun = review_listening_plan.arpabet("Y UW1 S IH0 Z", 1, weak=[2])
    dictionary = {**review_listening_plan.arpabet("Y UW1 Z IH0 Z", 1, weak=[2]), "basis": "CMU"}
    added = review_listening_plan.arpabet("Y UW1 Z IH0 Z", 1, weak=[2])
    monkeypatch.setattr(review_listening_plan, "HETERONYMS", {})
    monkeypatch.setattr(review_listening_plan, "MANDARIN_READINGS", {})
    monkeypatch.setattr(
        review_listening_plan, "EXTRA_VARIANTS", {"uses": {"verb": added}, "users": {"verb": added}}
    )
    targets = [
        {"term": "uses", "kind": "contextual-homograph", "lexical_stress": {"noun": noun}},
        {
            "term": "users",
            "kind": "contextual-homograph",
            "lexical_stress": {"noun": noun, "verb": dictionary},
        },
    ]
    contract = {
        "sources": [],
        "languages": {"Chinese": {"targets": []}, "English": {"targets": targets}},
    }
    extended, kept = review_listening_plan.analyst_contract(contract)["languages"]["English"][
        "targets"
    ]
    assert extended["lexical_stress"] == {"noun": noun, "verb": added}
    assert extended["variant_sources"] == {"verb": "analyst-inference"}
    assert kept["lexical_stress"] == {"noun": noun, "verb": dictionary}
    assert "variant_sources" not in kept


def test_an_occurrence_outside_every_thought_is_refused():
    target = {"term": "调度", "kind": "contextual-mandarin-word", "target_reading": "diàodù"}
    segment = {"id": "07", "text": "先看调度。", "utterance_groups": ["先看"]}
    with pytest.raises(ReviewError, match="07: 调度 at 2 lies outside every thought"):
        review_listening_plan.target_entries("zh", target, [segment])
