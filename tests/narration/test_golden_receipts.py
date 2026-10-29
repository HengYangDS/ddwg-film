"""Golden narration receipts: one retained record per edition reproduces from its sources.

The fixture holds metadata only, copied from the current receipts: Chinese segment 18 with a
declared repetition penalty and one thought retake, and English segment 28 with a segment
retake seed and two thought retakes. Every fingerprint and receipt hash below is a retained
value, so a change to any request input, key or serialized byte fails here first.
"""

import hashlib
import json
from pathlib import Path

import pytest

import filmkit.narration.pronunciation as narration_pronunciation
import filmkit.narration.retakes as narration_retakes
import filmkit.narration.thought_groups as narration_thought_groups
import filmkit.repository as repository
from filmkit.narration.voice_model import request_fingerprint

GOLDEN = json.loads((Path(__file__).parent / "golden/receipts.json").read_text())


@pytest.fixture(params=sorted(GOLDEN))
def golden(request) -> dict:
    return GOLDEN[request.param]


def cast_requests(golden: dict) -> tuple[dict, list[dict]]:
    """The parent and child requests that synthesis derives from the script and the cast."""
    segment, cast = golden["segment"], golden["cast"]
    thoughts = narration_pronunciation.native_utterance_plan(
        segment, {"normalization": golden["normalization"]}
    )
    seed, temperature, plan = narration_retakes.segment_take(segment, cast, thoughts)
    speech = narration_thought_groups.cast_speech(
        cast,
        language=golden["language"],
        contract_sha256=golden["pronunciation_contract_sha256"],
        seed=seed,
        temperature=temperature,
    )
    parent = narration_thought_groups.parent_request(
        segment["text"], segment["spoken_text"], speech, plan
    )
    settings = narration_thought_groups.group_settings(request_fingerprint(parent), speech)
    children = [
        narration_thought_groups.child_request(settings, thought, index)
        for index, thought in enumerate(plan, 1)
    ]
    return parent, children


def recorded_requests(record: dict) -> tuple[dict, list[dict]]:
    """The parent and child requests that validation derives from the retained record."""
    speech = narration_thought_groups.recorded_speech(record)
    parent = narration_thought_groups.parent_request(
        record["text"],
        record["spoken_text"],
        speech,
        narration_thought_groups.recorded_plan(record),
    )
    settings = narration_thought_groups.group_settings(record["fingerprint"], speech)
    children = [
        narration_thought_groups.child_request(
            settings,
            {key: child[key] for key in ("text", "spoken_text", "seed")},
            child["index"],
        )
        for child in record["utterance_groups"]["records"]
    ]
    return parent, children


@pytest.mark.parametrize(
    "derive",
    [cast_requests, lambda golden: recorded_requests(golden["record"])],
    ids=["from-script-and-cast", "from-record"],
)
def test_retained_fingerprints_reproduce(golden, derive):
    record = golden["record"]
    parent, requests = derive(golden)
    assert request_fingerprint(parent) == record["fingerprint"]
    retained = record["utterance_groups"]["records"]
    assert [request_fingerprint(request) for request in requests] == [
        child["fingerprint"] for child in retained
    ]
    # A child receipt starts with its request, in the request's key order.
    for request, child in zip(requests, retained, strict=True):
        assert list(child)[: len(request)] == list(request)


def test_child_receipts_rewrite_to_their_retained_bytes(golden, tmp_path):
    _, children = cast_requests(golden)
    for request, child in zip(
        children, golden["record"]["utterance_groups"]["records"], strict=True
    ):
        receipt = narration_thought_groups.child_receipt(
            request,
            path=child["path"],
            wav_sha256=child["wav_sha256"],
            frames=child["frames"],
            sample_rate=child["sample_rate"],
            native_chunks=child["native_chunks"],
        )
        repository.write(tmp_path / "receipt.json", receipt)
        written = (tmp_path / "receipt.json").read_bytes()
        assert hashlib.sha256(written).hexdigest() == child["receipt_sha256"]


def test_group_policy_is_the_retained_policy(golden):
    assert golden["record"]["utterance_groups"]["policy"] == narration_thought_groups.GROUP_POLICY
