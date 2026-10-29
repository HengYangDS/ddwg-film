"""The requests, receipts and joins of the thoughts a narration recording joins, and their check.

A segment is narrated as its authored thoughts, each a native recording of its own request.
The thoughts of one recording share its speech settings, and the recording's own request names
every thought, so its fingerprint binds the joined recording to all of them. Thoughts are
joined only with added quiet: at least `JOIN_QUIET_MINIMUM` seconds between two voices,
counting the quiet each recording already holds at the join. Validation derives every request
again from a retained record and checks each recording, receipt, request file and join against
it, so a reused recording is exactly the one its receipt names.
"""

from __future__ import annotations

import json
import re
import wave
from itertools import pairwise
from pathlib import Path

import numpy as np

import filmkit.repository as repository
from filmkit.narration.take_edges import ending
from filmkit.narration.voice_model import (
    MODEL,
    NATIVE_DECODER,
    NATIVE_STREAM,
    REVISION,
    request_fingerprint,
)

# Both values are request and receipt inputs: a change re-narrates every recording.
JOIN_QUIET_MINIMUM = 0.30
# A sample at most this far from zero, about -50 dBFS, is quiet at a thought's edge.
QUIET_SAMPLE_LIMIT = 104
GROUP_POLICY = (
    "Source-exact native complete thoughts; preserve all tails; "
    f"quiet minimum {JOIN_QUIET_MINIMUM:.2f}s"
)
# The speech settings that every thought of one recording shares, in receipt order; a cast
# that declares an ICL repetition penalty adds it last.
SPEECH_SETTINGS = (
    "reference_audio",
    "reference_sha256",
    "reference_text",
    "reference_treatment",
    "seed",
    "temperature",
    "max_tokens",
    "language",
    "model",
    "revision",
    "decoder",
    "stream",
    "pronunciation_contract_sha256",
)
# The settings a recording's own request names besides its text, reference and thoughts.
PARENT_SETTINGS = (
    "seed",
    "temperature",
    "max_tokens",
    "language",
    "model",
    "revision",
    "decoder",
    "stream",
)
DEFAULT_MAX_TOKENS = 1900
# A complete thought ends on a sentence end, before any closing quotes or brackets.
THOUGHT_ENDING = re.compile(r"[。！？.!?][\"'”’）)\]]*$")
JOIN_FRAMES = (
    "after_group",
    "source_sample",
    "native_quiet_frames",
    "added_quiet_frames",
    "removed_samples",
)


class RetainedUtteranceError(RuntimeError):
    """A retained recording, its receipt, request file or joins differ from what binds them."""


def authored_groups(section: dict) -> list[str]:
    """The section's authored thoughts: two or more, joining to its text, each one complete.

    Raises:
        ValueError: The section holds no such partition.
    """
    groups = section.get("utterance_groups")
    if (
        not isinstance(groups, list)
        or len(groups) < 2
        or any(not isinstance(text, str) or not text.strip() for text in groups)
        or "".join(groups) != section["text"]
        or any(not THOUGHT_ENDING.search(text.rstrip()) for text in groups)
    ):
        msg = "Utterance groups require exact text and complete thought endings"
        raise ValueError(msg)
    return groups


def cast_speech(
    cast: dict, *, language: str, contract_sha256: str, seed: int, temperature: float
) -> dict:
    """The speech settings a cast narrates one segment with."""
    speech = {
        "reference_audio": cast["reference_audio"],
        "reference_sha256": cast["reference_sha256"],
        "reference_text": cast["reference_text"],
        "reference_treatment": cast.get("reference_treatment"),
        "seed": seed,
        "temperature": temperature,
        "max_tokens": cast.get("full_narration_max_tokens", DEFAULT_MAX_TOKENS),
        "language": language,
        "model": MODEL,
        "revision": REVISION,
        "decoder": NATIVE_DECODER,
        "stream": NATIVE_STREAM,
        "pronunciation_contract_sha256": contract_sha256,
    }
    penalty = cast.get("icl_repetition_penalty")
    return speech if penalty is None else {**speech, "icl_repetition_penalty": penalty}


def recorded_speech(record: dict) -> dict:
    """The speech settings a retained record and its first thought declare."""
    first = record["utterance_groups"]["records"][0]
    speech = {
        "reference_audio": record["reference_audio"],
        "reference_sha256": record["reference_sha256"],
        "reference_text": first.get("reference_text"),
        "reference_treatment": record.get("reference_treatment"),
        "seed": record["seed"],
        "temperature": record["temperature"],
        "max_tokens": first.get("max_tokens"),
        "language": record["language"],
        "model": record["model"],
        "revision": record["revision"],
        "decoder": record["decoder"],
        "stream": record["stream"],
        "pronunciation_contract_sha256": record.get("pronunciation_contract_sha256"),
    }
    if "icl_repetition_penalty" in record:
        speech["icl_repetition_penalty"] = record["icl_repetition_penalty"]
    return speech


def recorded_plan(record: dict) -> list[dict]:
    """The thoughts a retained record's request names, each with its seed and run-on if retaken."""
    return [
        {
            "text": child["text"],
            "spoken_text": child["spoken_text"],
            **({"seed": child["seed"]} if child.get("seed") != record["seed"] else {}),
            **({"run_on": child["run_on"]} if "run_on" in child else {}),
        }
        for child in record["utterance_groups"]["records"]
    ]


def parent_request(text: str, spoken_text: str, speech: dict, plan: list[dict]) -> dict:
    """The request of a whole recording: its text, settings, thoughts and join quiet."""
    request = {
        "text": text,
        "spoken": spoken_text,
        "reference": speech["reference_sha256"],
        "reference_text": speech["reference_text"],
        **{key: speech[key] for key in PARENT_SETTINGS},
        "utterance_plan": plan,
        "join_quiet_minimum": JOIN_QUIET_MINIMUM,
        "pronunciation_contract": speech["pronunciation_contract_sha256"],
    }
    if "icl_repetition_penalty" in speech:
        request["icl_repetition_penalty"] = speech["icl_repetition_penalty"]
    return request


def group_settings(parent_fingerprint: str, speech: dict) -> dict:
    """The settings that each thought request of one recording shares, in receipt order."""
    settings = {
        "parent_fingerprint": parent_fingerprint,
        **{key: speech[key] for key in SPEECH_SETTINGS},
    }
    if "icl_repetition_penalty" in speech:
        settings["icl_repetition_penalty"] = speech["icl_repetition_penalty"]
    return settings


def child_request(settings: dict, thought: dict, index: int) -> dict:
    """The request of one thought: the shared settings, its texts and seed, and its place."""
    return {**settings, **thought, "index": index}


def child_receipt(
    request: dict,
    *,
    path: str,
    wav_sha256: str,
    frames: int,
    sample_rate: int,
    native_chunks: int,
    native_frames: int | None = None,
) -> dict:
    """The receipt of one thought recording: its request, fingerprint and retained PCM.

    A thought read on into its run-on records the frames of its native take before the cut.
    """
    return {
        **request,
        "fingerprint": request_fingerprint(request),
        "path": path,
        "wav_sha256": wav_sha256,
        "frames": frames,
        "sample_rate": sample_rate,
        "native_chunks": native_chunks,
        **({} if native_frames is None else {"native_frames": native_frames}),
        "post_pitch_transform": False,
        "post_tempo_transform": False,
    }


def quiet_edge(audio: np.ndarray, *, tail: bool) -> int:
    """The number of quiet samples at a recording's head, or at its tail."""
    occupied = np.flatnonzero(np.abs(audio.astype(np.int32)) > QUIET_SAMPLE_LIMIT)
    if not len(occupied):
        return len(audio)
    return int(len(audio) - 1 - occupied[-1] if tail else occupied[0])


def join_quiet(previous: np.ndarray, following: np.ndarray, rate: int) -> tuple[int, int]:
    """The quiet two thoughts already hold at their join, and the quiet the join adds."""
    native = quiet_edge(previous, tail=True) + quiet_edge(following, tail=False)
    return native, max(0, _minimum_join(rate) - native)


def _minimum_join(rate: int) -> int:
    return round(JOIN_QUIET_MINIMUM * rate)


def group_path(value: str, root: Path) -> Path:
    """Resolve a retained dependency without accepting aliases or foreign paths."""
    if not isinstance(value, str):
        msg = "Retained utterance path differs"
        raise TypeError(msg)
    path = Path(value)
    resolved = root / path
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.as_posix() != value
        or resolved.resolve() != resolved
        or not resolved.is_file()
        or resolved.is_symlink()
    ):
        msg = "Retained utterance path differs"
        raise RetainedUtteranceError(msg)
    return resolved


def retained_group(
    child: dict, inputs: dict, wave_path: Path, root: Path
) -> tuple[np.ndarray, Path]:
    """Validate a received thought against its independently expected request.

    Returns:
        The thought's PCM and its request file.
    """
    fingerprint = _check_request_inputs(child, inputs)
    pcm = _child_pcm(child, wave_path, root)
    return pcm, _received_request(wave_path, fingerprint, root)


def _check_request_inputs(child: dict, inputs: dict) -> str:
    """Check that a thought receipt holds its request exactly; return the request fingerprint."""
    if not isinstance(child, dict) or any(
        key not in child or type(child[key]) is not type(value) or child[key] != value
        for key, value in inputs.items()
    ):
        msg = "Retained utterance inputs differ"
        raise RetainedUtteranceError(msg)
    fingerprint = request_fingerprint(inputs)
    if child.get("fingerprint") != fingerprint:
        msg = "Retained utterance fingerprint differs"
        raise RetainedUtteranceError(msg)
    if (
        type(inputs.get("index")) is not int
        or inputs["index"] < 1
        or type(inputs.get("seed")) is not int
        or type(inputs.get("max_tokens")) is not int
        or inputs["max_tokens"] < 1
        or type(inputs.get("temperature")) not in (int, float)
        or not np.isfinite(inputs["temperature"])
    ):
        msg = "Retained utterance settings differ"
        raise RetainedUtteranceError(msg)
    return fingerprint


def _child_pcm(child: dict, wave_path: Path, root: Path) -> np.ndarray:
    """The PCM of a thought recording that still matches its receipt."""
    if group_path(child.get("path"), root) != wave_path:
        msg = "Retained utterance path differs"
        raise RetainedUtteranceError(msg)
    if repository.sha(wave_path) != child.get("wav_sha256"):
        msg = "Retained utterance input changed"
        raise RetainedUtteranceError(msg)
    if any(
        type(child.get(field)) is not int or child[field] <= 0
        for field in ("frames", "sample_rate", "native_chunks")
    ):
        msg = "Retained utterance PCM metadata differs"
        raise RetainedUtteranceError(msg)
    if (
        child.get("post_pitch_transform") is not False
        or child.get("post_tempo_transform") is not False
    ):
        msg = "Retained utterance transform differs"
        raise RetainedUtteranceError(msg)
    with wave.open(str(wave_path)) as audio:
        metadata = (
            audio.getnchannels(),
            audio.getsampwidth(),
            audio.getframerate(),
            audio.getnframes(),
        )
        if (
            metadata != (1, 2, child["sample_rate"], child["frames"])
            or child["frames"] <= child["sample_rate"]
        ):
            msg = "Retained utterance PCM metadata differs"
            raise RetainedUtteranceError(msg)
        pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
    if len(pcm) != child["frames"]:
        msg = "Retained utterance PCM metadata differs"
        raise RetainedUtteranceError(msg)
    if "run_on" in child and (
        child["run_on"].get("cut_sample") != child["frames"]
        or type(child.get("native_frames")) is not int
        or child["native_frames"] <= child["frames"]
        or not ending(pcm, child["sample_rate"])["natural"]
    ):
        msg = "Retained run-on take does not end naturally at its cut"
        raise RetainedUtteranceError(msg)
    return pcm


def _received_request(wave_path: Path, fingerprint: str, root: Path) -> Path:
    """The request file of a thought whose recording was received, not only started."""
    request = group_path(wave_path.with_suffix(".request.json").relative_to(root).as_posix(), root)
    if json.loads(request.read_text()) != {"state": "received", "fingerprint": fingerprint}:
        msg = "Unresolved native utterance; inspect before replay"
        raise RetainedUtteranceError(msg)
    return request


def validate_group_inputs(
    record: dict, *, root: Path | None = None, section: dict | None = None
) -> set[str]:
    """Bind a retained record's thoughts, text, PCM and joins to it; return its dependencies.

    The dependencies are the root-relative paths of the joined recording and of each thought's
    recording, receipt and request file. A record without thought groups has none. A section
    of the current script, when given, must still author the record's thoughts.
    """
    root = (repository.ROOT if root is None else root).resolve()
    _check_partition(record, section)
    if "utterance_groups" not in record:
        return set()
    children = _children(record, section)
    _check_parent_text(record, children)
    speech = recorded_speech(record)
    _check_speech(record, speech)
    _check_parent_fingerprint(record, speech)
    parent, pcm = _parent_pcm(record, root)
    joins = _joins(record, children)
    settings = group_settings(record["fingerprint"], speech)
    rate = record["sample_rate"]
    dependencies, recordings, cursor = {record["path"]}, [], 0
    for index, child in enumerate(children, 1):
        samples, request = _verify_child(child, index, settings, parent, root)
        _check_in_parent(child, samples, pcm, cursor, rate)
        recordings.append(samples)
        cursor += len(samples)
        dependencies.update((child["path"], child["receipt"], request.relative_to(root).as_posix()))
        if index < len(children):
            _check_join(joins[index - 1], index, cursor, pcm, rate)
            cursor += joins[index - 1]["added_quiet_frames"]
    if cursor != len(pcm):
        msg = "Retained utterance parent extent differs"
        raise RetainedUtteranceError(msg)
    _check_quiet_accounting(joins, recordings, rate)
    return dependencies


def _check_partition(record: dict, section: dict | None) -> None:
    """Check that the current section, when given, still authors the record's thoughts."""
    if section is None:
        return
    msg = "Retained utterance source groups differ"
    if ("utterance_groups" in section) != ("utterance_groups" in record):
        raise RetainedUtteranceError(msg)
    if "utterance_groups" in section:
        try:
            authored_groups(section)
        except ValueError as error:
            raise RetainedUtteranceError(msg) from error


def _children(record: dict, section: dict | None) -> list[dict]:
    """The record's thought receipts, each with its text and spoken text."""
    grouped = record["utterance_groups"]
    if (
        not isinstance(grouped, dict)
        or not isinstance(grouped.get("records"), list)
        or len(grouped["records"]) < 2
    ):
        msg = "Retained utterance records differ"
        raise RetainedUtteranceError(msg)
    children = grouped["records"]
    if any(
        not isinstance(child, dict)
        or any(
            not isinstance(child.get(key), str) or not child[key].strip()
            for key in ("text", "spoken_text")
        )
        for child in children
    ):
        msg = "Retained utterance records differ"
        raise RetainedUtteranceError(msg)
    if (
        section is not None
        and "utterance_groups" in section
        and [child["text"] for child in children] != section["utterance_groups"]
    ):
        msg = "Retained utterance source groups differ"
        raise RetainedUtteranceError(msg)
    return children


def _check_parent_text(record: dict, children: list[dict]) -> None:
    """Check that the thoughts join to the record's text and spoken text."""
    if (
        "".join(child["text"] for child in children) != record["text"]
        or "".join(child["spoken_text"] for child in children) != record["spoken_text"]
    ):
        msg = "Retained utterance text differs"
        raise RetainedUtteranceError(msg)


def _check_speech(record: dict, speech: dict) -> None:
    """Check the declared settings' types and the reference transcript's identity."""
    if not isinstance(speech["reference_text"], str):
        msg = "Retained utterance reference text differs"
        raise RetainedUtteranceError(msg)
    if (
        type(speech["max_tokens"]) is not int
        or speech["max_tokens"] <= 0
        or type(speech["seed"]) is not int
        or type(speech["temperature"]) not in (int, float)
        or not np.isfinite(speech["temperature"])
    ):
        msg = "Retained utterance settings differ"
        raise RetainedUtteranceError(msg)
    if repository.content_sha(speech["reference_text"]) != record["reference_text_sha256"]:
        msg = "Retained utterance reference text differs"
        raise RetainedUtteranceError(msg)


def _check_parent_fingerprint(record: dict, speech: dict) -> None:
    """Check that the record's request, derived again, reproduces its fingerprint."""
    request = parent_request(record["text"], record["spoken_text"], speech, recorded_plan(record))
    if request_fingerprint(request) != record["fingerprint"]:
        msg = "Retained utterance parent fingerprint differs"
        raise RetainedUtteranceError(msg)


def _parent_pcm(record: dict, root: Path) -> tuple[Path, np.ndarray]:
    """The joined recording and its PCM, still matching the record."""
    if type(record.get("sample_rate")) is not int or record["sample_rate"] <= 0:
        msg = "Retained parent PCM metadata differs"
        raise RetainedUtteranceError(msg)
    parent = group_path(record["path"], root)
    with wave.open(str(parent)) as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (
            1,
            2,
            record["sample_rate"],
        ):
            msg = "Retained parent PCM metadata differs"
            raise RetainedUtteranceError(msg)
        pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
    if repository.sha(parent) != record["wav_sha256"]:
        msg = "Retained parent waveform changed"
        raise RetainedUtteranceError(msg)
    return parent, pcm


def _joins(record: dict, children: list[dict]) -> list:
    """The record's joins, one after each thought but the last."""
    joins = record["utterance_groups"].get("joins")
    if not isinstance(joins, list) or len(joins) != len(children) - 1:
        msg = "Retained utterance joins differ"
        raise RetainedUtteranceError(msg)
    return joins


def _verify_child(
    child: dict, index: int, settings: dict, parent: Path, root: Path
) -> tuple[np.ndarray, Path]:
    """Check one thought's embedded receipt against its retained receipt and request.

    Returns:
        The thought's PCM and its request file.
    """
    if type(child.get("seed")) is not int:
        msg = "Retained utterance settings differ"
        raise RetainedUtteranceError(msg)
    thought = {key: child[key] for key in ("text", "spoken_text", "seed", "run_on") if key in child}
    request = child_request(settings, thought, index)
    expected = parent.with_suffix("") / f"{index:02d}-{request_fingerprint(request)[:12]}.wav"
    receipt = group_path(child.get("receipt"), root)
    if receipt != expected.with_suffix(".json") or repository.sha(receipt) != child.get(
        "receipt_sha256"
    ):
        msg = "Retained utterance input changed"
        raise RetainedUtteranceError(msg)
    retained = json.loads(receipt.read_text())
    embedded = {
        key: value
        for key, value in child.items()
        if key not in ("receipt", "receipt_sha256", "start_sample")
    }
    if (
        not isinstance(retained, dict)
        or embedded.keys() != retained.keys()
        or any(
            type(value) is not type(retained[key]) or value != retained[key]
            for key, value in embedded.items()
        )
    ):
        msg = "Retained utterance receipt differs"
        raise RetainedUtteranceError(msg)
    return retained_group(retained, request, expected, root)


def _check_in_parent(
    child: dict, samples: np.ndarray, pcm: np.ndarray, cursor: int, rate: int
) -> None:
    """Check that a thought's PCM stands unchanged at its place in the joined recording."""
    if child["sample_rate"] != rate:
        msg = "Retained utterance sample rate differs"
        raise RetainedUtteranceError(msg)
    if (
        type(child.get("start_sample")) is not int
        or child["start_sample"] != cursor
        or not np.array_equal(pcm[cursor : cursor + len(samples)], samples)
    ):
        msg = "Retained utterance PCM differs from parent"
        raise RetainedUtteranceError(msg)


def _check_join(join: dict, after_group: int, cursor: int, pcm: np.ndarray, rate: int) -> None:
    """Check that a join starts where its thought ends and adds only digital quiet."""
    if (
        not isinstance(join, dict)
        or any(type(join.get(key)) is not int for key in JOIN_FRAMES)
        or join["after_group"] != after_group
        or join["source_sample"] != cursor
        or join["removed_samples"] != 0
        or join["native_quiet_frames"] < 0
        or join["added_quiet_frames"] < 0
        or join["native_quiet_frames"] + join["added_quiet_frames"] < _minimum_join(rate)
        or np.any(pcm[cursor : cursor + join["added_quiet_frames"]])
    ):
        msg = "Retained utterance join differs"
        raise RetainedUtteranceError(msg)


def _check_quiet_accounting(joins: list, recordings: list[np.ndarray], rate: int) -> None:
    """Check that each join records the quiet its thoughts hold and the quiet it added."""
    for join, (previous, following) in zip(joins, pairwise(recordings), strict=True):
        if (join["native_quiet_frames"], join["added_quiet_frames"]) != join_quiet(
            previous, following, rate
        ):
            msg = "Retained utterance quiet accounting differs"
            raise RetainedUtteranceError(msg)
