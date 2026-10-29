"""Caption phrasing for both editions."""

import json

import pytest

import filmkit.captions.chinese as captions_chinese
import filmkit.captions.english as captions_english
import filmkit.captions.phrasing as captions_phrasing
import filmkit.repository as repository


def test_english_caption_cues_preserve_connected_text_and_punctuation():
    copy = (
        "Before temporary work enters production, verify meaning, quality, "
        "permissions, and reproducibility for that use. "
        "Limited use still requires evidence and permission."
    )
    cues = captions_phrasing.segment_caption_phrases({"text": copy}, "en")
    assert "".join(cues) == copy
    assert all("\n" not in cue and len(cue) <= 66 for cue in cues)
    assert all(cue[0].isalpha() for cue in cues)
    with pytest.raises(ValueError, match="complete exact"):
        captions_phrasing.segment_caption_phrases(
            {"text": copy, "caption_phrases": ["Unrelated caption."]}, "en"
        )


def test_chinese_captions_preserve_the_exact_source():
    phrases = captions_chinese.caption_phrases("记录到了，能否使用？")
    assert "".join(phrases) == "记录到了，能否使用？"
    assert all("\n" not in phrase and len(phrase) <= 33 for phrase in phrases)


def test_authored_captions_preserve_complete_semantic_sentence():
    segment = {
        "text": ("工作应解决问题、检验判断及限度、改善下一次，这是三种结果，不是三份报告。"),
        "caption_phrases": [
            "工作应解决问题、检验判断及限度、改善下一次，",
            "这是三种结果，不是三份报告。",
        ],
    }
    assert captions_phrasing.segment_caption_phrases(segment, "zh") == segment["caption_phrases"]
    with pytest.raises(ValueError, match="complete exact"):
        captions_phrasing.segment_caption_phrases(
            {**segment, "caption_phrases": ["不是三份报告。"]}, "zh"
        )


def test_chinese_caption_cues_count_visible_punctuation():
    passage = "范围和非目标，接收方、地点、格式、详略，期限、安全、兼容、成本限制，"
    cues = captions_phrasing.segment_caption_phrases({"text": passage}, "zh")
    assert "".join(cues) == passage
    assert all(len(cue) <= 33 and "\n" not in cue for cue in cues)
    assert all(cue[-1] in "，。；：！？、" for cue in cues)


def test_english_captions_keep_complements_and_rebalance_short_tails():
    passages = [
        (
            "Fidelity preserves meaning, facts, and relationships without distortion, "
            "keeping sources, contrary evidence, uncertainty, "
            "failure, and limits clear. "
        ),
        "Writing applies these aims: titles name subject, purpose, and status. ",
        (
            "Define terms; use precise verbs, concrete nouns, a measured tone, "
            "and one point per paragraph. "
        ),
    ]
    for passage in passages:
        cues = captions_english.english_caption_phrases(passage)
        assert "".join(cues) == passage
        assert all(len(cue) <= 66 and "\n" not in cue for cue in cues)
        assert all(len(cue.split()) >= 3 for cue in cues)
        assert not any(cue.rstrip().endswith(("without", "and", "per")) for cue in cues)
        assert not any(
            cue.strip() in {"status.", "per paragraph.", "Define terms;"} for cue in cues
        )


@pytest.mark.parametrize(
    ("passage", "connected_phrase"),
    [
        (
            (
                "Local tests pass, but a report joins on the old identifier "
                "and may mismatch or lose entities."
            ),
            "old identifier",
        ),
        (
            (
                "Checked Agent output becomes a durable team fact only when its "
                "underlying source and limits enter the work’s authoritative system."
            ),
            "team fact",
        ),
        (
            "Retirement needs verified consumer migration or authorized withdrawal.",
            "consumer migration",
        ),
    ],
)
def test_english_caption_reflow_preserves_phrases_at_clause_boundaries(passage, connected_phrase):
    cues = captions_phrasing.segment_caption_phrases({"text": passage}, "en")
    assert "".join(cues) == passage
    assert all(len(cue) <= 66 and "\n" not in cue for cue in cues)
    assert any(connected_phrase in cue for cue in cues)
    assert all(len(cue.split()) >= 3 for cue in cues)


@pytest.mark.parametrize(
    ("passage", "closing_punctuation"),
    [
        (
            (
                "Answer first; honestly say “I don’t know.” "
                "Revise immediately when evidence overturns a position."
            ),
            ".”",
        ),
        (
            (
                "Use checkable statements: “Tests passed; the release owner must "
                "confirm the target environment before release.” "
                "Contrast “actively progressing,” which gives no next action."
            ),
            ".”",
        ),
        (
            'Answer honestly: "Is this current?" Verify the bound source.',
            '?"',
        ),
        (
            "Check its identity (including version!). Verify use.",
            "!).",
        ),
    ],
)
def test_english_caption_reflow_keeps_closing_punctuation_with_its_sentence(
    passage, closing_punctuation
):
    cues = captions_phrasing.segment_caption_phrases({"text": passage}, "en")
    assert "".join(cues) == passage
    assert any(closing_punctuation in cue for cue in cues)
    assert all(len(cue) <= 66 and "\n" not in cue for cue in cues)
    assert all(any(character.isalnum() for character in cue) for cue in cues)
    assert not any(cue.lstrip().startswith(("”", ")", "]", "}")) for cue in cues)
    thoughts = captions_english.english_caption_sentences(passage)
    assert "".join(thoughts) == passage
    assert not any(group.lstrip().startswith(("”", ")", "]", "}")) for group in thoughts)


def test_english_caption_reflow_preserves_every_current_paragraph():
    script = json.loads((repository.ROOT / "content/en/film-script.json").read_text())
    for segment in script["segments"]:
        cues = captions_english.english_caption_phrases(segment["text"])
        assert "".join(cues) == segment["text"]
        assert all(len(cue) <= 66 and "\n" not in cue for cue in cues)
        assert all(any(character.isalnum() for character in cue) for cue in cues)
        assert (
            captions_phrasing.segment_caption_phrases(
                {"text": segment["text"], "caption_phrases": cues}, "en"
            )
            == cues
        )


def test_english_captions_keep_bound_words_with_their_phrase():
    # Round-9 review EN9-11: no line ends on a word that binds to what follows, and a
    # function word that closes its own phrase stays on the line it closes.
    sentences = {
        "Prefer the smallest experiment that separates the likely explanations. ": ("that"),
        "A feed that is accurate today cannot prove what was available back then. ": ("cannot"),
        "Development and verification are two activities within one responsibility. ": ("two"),
        "Even checked output becomes a lasting team fact only once its source "
        "and limits are recorded in the authoritative record. ": "only",
    }
    for sentence, bound in sentences.items():
        cues = captions_english.english_caption_phrases(sentence)
        assert "".join(cues) == sentence
        assert len(cues) > 1
        assert not any(cue.split()[-1] in {bound, "once"} for cue in cues), cues
    stranded = (
        "The guidelines bind members, and the Agents that members delegate to: "
        "AI systems that search, reason and act toward a goal. "
    )
    cues = captions_english.english_caption_phrases(stranded)
    assert any(cue.rstrip().endswith("delegate to:") for cue in cues), cues


def test_chinese_captions_end_lists_at_their_own_punctuation():
    # Round-11 review R11-2: a cue does not end inside an enumeration at 、 when a
    # comma, semicolon or colon break keeps the cues within the limit, and a brief
    # closing clause rides on its line instead of standing alone.
    passages = {
        "智能体自己也要先确认任务、目标、现状和负责人，"
        "按可逆、可核验的小步推进，不顺手改无关的内容；": [
            "智能体自己也要先确认任务、目标、现状和负责人，",
            "按可逆、可核验的小步推进，不顺手改无关的内容；",
        ],
        "判断讲明标准、把握和限度，决定写明谁定的、怎样取舍、"
        "什么情况下重新审议，行动落到负责人、期限和完成条件。": [
            "判断讲明标准、把握和限度，",
            "决定写明谁定的、怎样取舍、什么情况下重新审议，",
            "行动落到负责人、期限和完成条件。",
        ],
        "改动之前，核对实际的目标、版本、环境、现状、并行的工作和恢复路径。": [
            "改动之前，核对实际的目标、版本、环境、现状、并行的工作和恢复路径。"
        ],
        "目标、事实来源、负责人、权限或者不可逆的后果说不清，就停下来问。": [
            "目标、事实来源、负责人、权限或者不可逆的后果说不清，就停下来问。"
        ],
        # A list with no other break still ends at 、 rather than leaving a brief
        # line, and a passage without such a choice keeps its earlier lines.
        "没人用的、失去适用对象的、重复事实来源的、成本高过收益的规则，就废止。": [
            "没人用的、失去适用对象的、重复事实来源的、",
            "成本高过收益的规则，就废止。",
        ],
        "如果发布准时，任务却启动得晚，问题就可能出在调度上，这是推论，还要排除别的解释。": [
            "如果发布准时，任务却启动得晚，问题就可能出在调度上，",
            "这是推论，还要排除别的解释。",
        ],
    }
    for passage, expected in passages.items():
        assert captions_chinese.caption_phrases(passage) == expected


@pytest.mark.parametrize(
    ("passage", "phrases"),
    [
        (
            (
                "High-risk use admission, permission changes, production releases, "
                "deletion or overwrite, and irreversible actions need the authorized "
                "decision owner's approval. "
            ),
            ["irreversible actions", "decision owner's"],
        ),
        (
            (
                "Stop and escalate, too, when another person's unrecognized or "
                "uncommitted work, or work of unknown ownership, appears; or when "
                "continuing would hide a failure, pollute a source of truth, make the "
                "harm worse, or present a guess as fact. "
            ),
            ["unrecognized or uncommitted work", "source of truth"],
        ),
        (
            (
                "When a data error, a production failure, or a permission or compliance "
                "breach threatens people, data, production, downstream use or "
                "compliance, whoever finds it contains it within their authority and "
                "tells the responsible owner. "
            ),
            ["permission or compliance breach", "contains it"],
        ),
        (
            (
                "A target without time, cost, compliance, technical and resource limits "
                "is not yet an executable commitment. "
            ),
            ["technical and resource limits"],
        ),
        (
            (
                "Changes to production, shared assets or critical management chains "
                "also need a defined subject, impact, task lead and authority; "
                "replayable inputs, logic, versions and outputs; tests, acceptance "
                "against agreed criteria and operational observation; and a release "
                "window with a rollback or degradation path. "
            ),
            ["agreed criteria"],
        ),
        (
            (
                "Checking the vendor's publication time separates two explanations: "
                "did the vendor publish late, or did our job start late? "
            ),
            ["publication time", "separates two explanations"],
        ),
        (
            (
                "An authorized person and a clear subject lead to a commitment and its "
                "boundary; then bounded action. "
            ),
            ["lead to a commitment"],
        ),
        (
            (
                "Within the stated boundaries, the responsible person closest to the "
                "facts chooses the method, tools and path. "
            ),
            ["person closest to the facts"],
        ),
        (
            (
                "Instead of “actively progressing”, say: the tests pass, and the "
                "release owner still needs to confirm the target environment. "
            ),
            ["needs to confirm"],
        ),
        # A modifier that takes a complement keeps the infinitive whole.
        (
            "And leave the system better able to catch and handle the next occurrence. ",
            ["to catch and handle the next occurrence"],
        ),
        # Round-13 review EN13-7: modifiers joined by "and" share their noun, a verb
        # keeps the "as" phrase it takes, and an instruction keeps the infinitive it
        # gives its object.
        (
            "For example: compare the vendor's earlier and revised price snapshots, read-only. ",
            ["the vendor's earlier and revised price snapshots"],
        ),
        (
            (
                "No fluency, effort or Agent efficiency offsets risks like these: "
                "fabricated, selectively hidden or unverified facts presented as "
                "established, completion claimed without current verification, Agent "
                "output standing in for fact, authorization or responsibility. "
            ),
            ["fabricated, selectively hidden or unverified facts", "presented as established"],
        ),
        (
            "Telling an Agent to “just handle it” does not set an authorization boundary. ",
            ["Telling an Agent to “just handle it”"],
        ),
        # Round-20 review EN20-13: a compound noun, a verb with its destination and a
        # listed phrase each stay in one cue.
        (
            (
                "For example: compare the vendor's earlier and revised price snapshots "
                "without changing anything. "
            ),
            ["price snapshots"],
        ),
        (
            (
                "If the agreed conditions are unmet, the work goes back to the member for "
                "revision within the delegation boundary. "
            ),
            ["goes back to the member"],
        ),
        (
            (
                "Fluency, effort and Agent efficiency never make up for risks like these: "
                "fabricated, selectively hidden or unverified facts presented as "
                "established, completion claimed without current verification, Agent "
                "output standing in for fact, authorization or responsibility, high-risk "
                "or irreversible action beyond authority, hidden blockers and failures. "
            ),
            ["Agent output", "standing in for fact, authorization or responsibility"],
        ),
        (
            (
                "This film follows the Data Department Work Guidelines in seven parts. "
                "It starts with why the work matters, then covers how to do it. "
            ),
            ["Data Department Work Guidelines"],
        ),
        (
            (
                "With the problem, scope or completion condition still missing, work is "
                "unframed. With a route and an owner but no action yet, it is planned. "
            ),
            ["the problem, scope or completion condition"],
        ),
    ],
)
def test_english_captions_keep_modifiers_terms_and_objects_whole(passage, phrases):
    # Round-11 review EN11-1: a modifier stays with its noun, a fixed term stays
    # whole, and a verb keeps its particle and the object it takes.
    cues = captions_english.english_caption_phrases(passage)
    assert "".join(cues) == passage
    assert all(len(cue) <= 66 and "\n" not in cue for cue in cues)
    for phrase in phrases:
        assert any(phrase in cue for cue in cues), cues


def test_english_caption_reflow_refuses_straddled_complete_thoughts():
    passage = (
        "Use the smallest sufficient model, revising it as evidence changes. "
        "Before collecting information, state which judgment it could change."
    )
    straddled = [
        "Use the smallest sufficient model, ",
        "revising it as evidence changes. Before collecting information, ",
        "state which judgment it could change.",
    ]
    with pytest.raises(ValueError, match="thought-group"):
        captions_phrasing.segment_caption_phrases(
            {"text": passage, "caption_phrases": straddled}, "en"
        )

    clauses = (
        "Admission sets acceptance criteria, permissions, limits, veto and exit; "
        "lineage records data sources and transformations."
    )
    cues = captions_phrasing.segment_caption_phrases({"text": clauses}, "en")
    assert "".join(cues) == clauses
    assert all(len(cue) <= 66 and "\n" not in cue for cue in cues)
    assert all(";" not in cue.rstrip()[:-1] for cue in cues)

    qualified = "Compare e.g. records and entities at ratio 1.5: units matter. Verify use."
    cues = captions_english.english_caption_phrases(qualified)
    assert "".join(cues) == qualified
    assert any("e.g." in cue for cue in cues)
    assert any("1.5:" in cue for cue in cues)
    assert not any("matter. Verify" in cue for cue in cues)
