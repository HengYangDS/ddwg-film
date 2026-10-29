"""Exact script edits that keep the narration mirrors, spoken texts and retakes bound."""

import copy
import hashlib
import json

import pytest

import filmkit.narration.script_edits as narration_script_edits
import filmkit.repository as repository

OPEN_SPEC = {"display": "OpenSpec", "spoken": "Open Spec", "kind": "english-name"}


def retake(seed: int, text: str) -> dict:
    return {"seed": seed, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}


SCRIPT = {"01": ["第一句。", "第二句。"], "02": ["甲句。乙句。", "丙句。"]}
RETAKES = {
    "01": {"groups": {"1": retake(7, "第一句。"), "2": retake(5, "第二句。")}},
    "02": {"seed": 9228, "groups": {"2": retake(9, "丙句。")}},
}


def write_edits(root, edits: dict) -> None:
    (root / "edits.json").write_text(json.dumps(edits, ensure_ascii=False))


def test_edit_script_replaces_and_splits_thoughts_and_rebinds_retakes(
    tmp_path, write_edition, capsys
):
    paths = write_edition("zh", SCRIPT, RETAKES)
    write_edits(
        tmp_path,
        {"replace": {"zh": [["01.1", "第一", "首"]]}, "split": {"zh": [["02.1", "甲句。"]]}},
    )
    before = {name: path.read_bytes() for name, path in paths.items()}
    narration_script_edits.main(["--edits", "edits.json", "--dry-run"])
    planned = json.loads(capsys.readouterr().out)
    assert {name: path.read_bytes() for name, path in paths.items()} == before

    narration_script_edits.main(["--edits", "edits.json"])
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is False
    assert report["editions"] == planned["editions"]
    assert report["editions"] == {
        "zh": [
            {
                "segment": "01",
                "thoughts_before": 2,
                "thoughts_after": 2,
                "new_thoughts": [1],
                "retakes_moved": {"2": 5},
                "retakes_released": ["1"],
            },
            {
                "segment": "02",
                "thoughts_before": 2,
                "thoughts_after": 3,
                "new_thoughts": [1, 2],
                "retakes_moved": {"3": 9},
                "retakes_released": [],
            },
        ]
    }
    segments = repository.read(paths["script"])["segments"]
    assert [s["utterance_groups"] for s in segments] == [
        ["首句。", "第二句。"],
        ["甲句。", "乙句。", "丙句。"],
    ]
    assert [(s["text"], s["spoken_text"]) for s in segments] == [
        ("首句。第二句。", "首句。第二句。"),
        ("甲句。乙句。丙句。", "甲句。乙句。丙句。"),
    ]
    assert paths["mirror"].read_text() == "首句。第二句。\n\n甲句。乙句。丙句。\n"
    assert repository.read(paths["cast"])["retakes"] == {
        "01": {"groups": {"2": retake(5, "第二句。")}},
        "02": {"seed": 9228, "groups": {"3": retake(9, "丙句。")}},
    }


def test_an_edited_segment_speaks_through_the_pronunciation_contract(tmp_path, write_edition):
    paths = write_edition("zh", SCRIPT, RETAKES, normalization=[OPEN_SPEC])
    write_edits(tmp_path, {"replace": {"zh": [["01.1", "第一", "OpenSpec "]]}})
    narration_script_edits.main(["--edits", "edits.json"])
    segment = repository.read(paths["script"])["segments"][0]
    assert segment["text"] == "OpenSpec 句。第二句。"
    assert segment["spoken_text"] == "Open Spec 句。第二句。"


@pytest.mark.parametrize(
    ("edits", "refusal"),
    [
        (
            {"replace": {"zh": [["01.1", "第一", "首"]], "en": [["01.1", "Two", "2"]]}},
            "en 01.1: phrase not found exactly once",
        ),
        ({"split": {"zh": [["01.2", "第二句。"]]}}, "zh 01.2: seam not found"),
        ({"replace": {"zh": [["01.3", "第", "首"]]}}, "zh 01.3: no such thought"),
        ({"replace": {"fr": []}}, "maps"),
    ],
)
def test_edit_script_refuses_without_writing_either_edition(
    tmp_path, write_edition, edits, refusal
):
    paths = [
        *write_edition("zh", SCRIPT, RETAKES).values(),
        *write_edition("en", {"01": ["One.", "Three."]}, {}).values(),
    ]
    write_edits(tmp_path, edits)
    before = [path.read_bytes() for path in paths]
    with pytest.raises(ValueError, match=refusal):
        narration_script_edits.main(["--edits", "edits.json"])
    assert [path.read_bytes() for path in paths] == before


def test_an_edit_returns_new_documents_and_leaves_its_inputs_unchanged():
    script = {
        "segments": [
            {
                "id": "02",
                "text": "甲句。乙句。丙句。",
                "spoken_text": "甲句。乙句。丙句。",
                "utterance_groups": ["甲句。乙句。", "丙句。"],
            }
        ]
    }
    cast = {"retakes": copy.deepcopy(RETAKES)}
    inputs = copy.deepcopy((script, cast))
    edited, recast, changed = narration_script_edits.edit(
        script,
        cast,
        [["02.2", "丙", "丁"]],
        [["02.1", "甲句。"]],
        contract={"normalization": []},
        code="zh",
    )
    assert (script, cast) == inputs
    assert edited["segments"][0]["utterance_groups"] == ["甲句。", "乙句。", "丁句。"]
    assert edited["segments"][0]["text"] == "甲句。乙句。丁句。"
    assert recast["retakes"]["02"] == {"seed": 9228, "groups": {}}
    assert changed == [
        {
            "segment": "02",
            "thoughts_before": 2,
            "thoughts_after": 3,
            "new_thoughts": [1, 2, 3],
            "retakes_moved": {},
            "retakes_released": ["2"],
        }
    ]
