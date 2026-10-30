"""Fixtures shared by the narration tests, and the speech runtime and host tool gates."""

import hashlib
import json
import shutil
import subprocess
import sys
import wave
from typing import NamedTuple

import numpy as np
import pytest

import filmkit.delivery.documents_folder as delivery_documents_folder
from filmkit.narration.thought_groups import join_quiet
from filmkit.narration.voice_model import MODEL, NATIVE_DECODER, REVISION

# Test modules whose code under test imports the MLX speech runtime at module load.
SPEECH_RUNTIME_MODULES = [
    "narration/test_alignment.py",
    "narration/test_audition.py",
    "narration/test_group_generation.py",
    "narration/test_synthesis.py",
    "narration/test_transcription.py",
]


def speech_runtime() -> bool:
    """Whether the MLX speech runtime loads, which needs a Metal device.

    A failed import of mlx.core aborts a later attempt in the same process, so a child
    process probes.
    """
    probe = subprocess.run(
        [sys.executable, "-c", "import mlx.core"], capture_output=True, check=False, timeout=120
    )
    return probe.returncode == 0


# Modules that run the speech model are collected only where its runtime loads. The header
# and the summary of every run name the modules a run without it leaves out.
collect_ignore = [] if speech_runtime() else SPEECH_RUNTIME_MODULES


class HostTool(NamedTuple):
    """A host tool that the tests marked with its marker run."""

    name: str
    runs: str
    present: bool


def rsync_3() -> bool:
    """Whether the rsync on PATH is the rsync 3 that delivery requires."""
    return bool(shutil.which("rsync")) and delivery_documents_folder.rsync_version().startswith(
        delivery_documents_folder.RSYNC_3
    )


# Production runs host tools that Homebrew installs and the locked toolchain does not supply:
# FFmpeg with VideoToolbox, and rsync 3 for delivery, since macOS's own rsync is openrsync. Tests
# marked with a tool's marker run it and are skipped where it is not on PATH; the header and the
# summary of every run name the tests it skips.
HOST_TOOLS = {
    "ffmpeg": HostTool(
        "host FFmpeg",
        "the host FFmpeg and FFprobe",
        all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")),
    ),
    "rsync": HostTool("host rsync 3", "the host rsync 3", rsync_3()),
}
host_skipped: dict[str, list[str]] = {marker: [] for marker in HOST_TOOLS}


def pytest_configure(config) -> None:
    """Register the markers of the tests that run a host tool."""
    for marker, tool in HOST_TOOLS.items():
        config.addinivalue_line("markers", f"{marker}: runs {tool.runs}")


def pytest_collection_modifyitems(items) -> None:
    """Skip the tests that run a host tool where it is not on PATH."""
    for marker, tool in HOST_TOOLS.items():
        if tool.present:
            continue
        skip = pytest.mark.skip(reason=f"the {tool.name} is not on PATH")
        for item in items:
            if item.get_closest_marker(marker):
                item.add_marker(skip)
                host_skipped[marker].append(item.nodeid)


def pytest_report_header() -> list[str]:
    speech = (
        f"speech runtime: absent; not collected: {', '.join(collect_ignore)}"
        if collect_ignore
        else "speech runtime: present; every speech runtime module collected"
    )
    tools = [
        f"{tool.name}: present; every test marked {marker} runs"
        if tool.present
        else f"{tool.name}: absent; the tests marked {marker} are skipped"
        for marker, tool in HOST_TOOLS.items()
    ]
    return [speech, *tools]


def pytest_terminal_summary(terminalreporter) -> None:
    if collect_ignore:
        terminalreporter.write_sep(
            "!",
            f"speech runtime absent: {len(collect_ignore)} test modules not collected",
            yellow=True,
        )
        for module in collect_ignore:
            terminalreporter.write_line(f"not collected: tests/{module}")
    for marker, skipped in host_skipped.items():
        if not skipped:
            continue
        terminalreporter.write_sep(
            "!", f"{HOST_TOOLS[marker].name} absent: {len(skipped)} tests skipped", yellow=True
        )
        for test in skipped:
            terminalreporter.write_line(f"skipped: {test}")


def write_pcm(path, pcm, rate) -> None:
    """Write mono 16-bit PCM as a WAV file, as the narration receipts record it."""
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(np.asarray(pcm, dtype="<i2").tobytes())


GROUP_SETTINGS = {
    "reference_audio": "reference.wav",
    "reference_text": "Reference.",
    "reference_treatment": None,
    "seed": 1,
    "temperature": 0.46,
    "max_tokens": 1900,
    "language": "English",
    "model": MODEL,
    "revision": REVISION,
    "decoder": NATIVE_DECODER,
    "stream": False,
    "pronunciation_contract_sha256": "c" * 64,
}


def retained_record(root, plans: list[dict], pcms: list[np.ndarray]) -> tuple[dict, dict]:
    """Retain thought recordings of the given PCM, joined with only added quiet, and their receipts.

    A thought whose plan reads on into its run-on records the frames of its native take, which
    are its own frames plus those cut after them, as many again here.

    Returns:
        The joined recording's record and the speech settings its thoughts share.
    """
    reference = root / "reference.wav"
    write_pcm(reference, np.full(24000, 300, dtype=np.int16), 24000)
    settings = {
        **GROUP_SETTINGS,
        "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
    }
    text = "".join(plan["text"] for plan in plans)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "text": text,
                "spoken": text,
                "reference": settings["reference_sha256"],
                "reference_text": settings["reference_text"],
                **{
                    key: settings[key]
                    for key in (
                        "seed",
                        "temperature",
                        "max_tokens",
                        "language",
                        "model",
                        "revision",
                        "decoder",
                        "stream",
                    )
                },
                "utterance_plan": plans,
                "join_quiet_minimum": 0.30,
                "pronunciation_contract": settings["pronunciation_contract_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    parent = root / "build/audio" / f"26-{fingerprint[:12]}.wav"
    parent.with_suffix("").mkdir(parents=True)
    records, pieces, joins, cursor = [], [], [], 0
    for index, (plan, pcm) in enumerate(zip(plans, pcms, strict=True), 1):
        inputs = {"parent_fingerprint": fingerprint, **settings, **plan, "index": index}
        child_hash = hashlib.sha256(
            json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        path = parent.with_suffix("") / f"{index:02d}-{child_hash[:12]}.wav"
        write_pcm(path, pcm, 24000)
        child = {
            **inputs,
            "fingerprint": child_hash,
            "path": path.relative_to(root).as_posix(),
            "wav_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "frames": len(pcm),
            "sample_rate": 24000,
            "native_chunks": 1,
            **({"native_frames": 2 * len(pcm)} if "run_on" in plan else {}),
            "post_pitch_transform": False,
            "post_tempo_transform": False,
        }
        receipt = path.with_suffix(".json")
        receipt.write_text(json.dumps(child))
        path.with_suffix(".request.json").write_text(
            json.dumps({"state": "received", "fingerprint": child_hash})
        )
        if pieces:
            native, added = join_quiet(pcms[index - 2], pcm, 24000)
            joins.append(
                {
                    "after_group": index - 1,
                    "source_sample": cursor,
                    "native_quiet_frames": native,
                    "added_quiet_frames": added,
                    "removed_samples": 0,
                    "listening_accepted": False,
                }
            )
            pieces.append(np.zeros(added, dtype=np.int16))
            cursor += added
        records.append(
            {
                **child,
                "receipt": receipt.relative_to(root).as_posix(),
                "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                "start_sample": cursor,
            }
        )
        pieces.append(pcm)
        cursor += len(pcm)
    write_pcm(parent, np.concatenate(pieces), 24000)
    record = {
        "id": "26",
        "text": text,
        "spoken_text": text,
        "fingerprint": fingerprint,
        "path": parent.relative_to(root).as_posix(),
        "wav_sha256": hashlib.sha256(parent.read_bytes()).hexdigest(),
        **{
            key: value
            for key, value in settings.items()
            if key not in ("reference_text", "max_tokens")
        },
        "reference_text_sha256": hashlib.sha256(settings["reference_text"].encode()).hexdigest(),
        "sample_rate": 24000,
        "duration": cursor / 24000,
        "utterance_groups": {"records": records, "joins": joins, "listening_accepted": False},
    }
    return record, settings


@pytest.fixture
def retained_group_record(tmp_path):
    """Construct native PCM and exact receipts without loading a speech model."""
    plans = [{"text": text, "spoken_text": text} for text in ("First thought.", " Second thought.")]
    pcms = [np.full(48000, 1000 * index, dtype=np.int16) for index in (1, 2)]
    record, settings = retained_record(tmp_path, plans, pcms)
    return tmp_path, record, plans, settings


def dying(frames: int, rate: int = 24000) -> np.ndarray:
    """A 16-bit voice that holds and then dies away over its last 0.3 s, ending naturally."""
    tail = round(0.3 * rate)
    envelope = np.concatenate([np.ones(frames - tail), np.exp(-np.arange(tail) / (0.03 * rate))])
    tone = np.sin(2 * np.pi * 180 * np.arange(frames) / rate) * 0.3 * envelope
    return (tone * 32767).astype(np.int16)


@pytest.fixture
def run_on_record(tmp_path):
    """Build a retained recording whose second thought was read on into the words after it.

    The second thought's take ends as its PCM ends: dying away, or cut while voiced.
    """

    def build(*, natural: bool = True):
        plans = [
            {"text": "First thought.", "spoken_text": "First thought."},
            {
                "text": " Second thought.",
                "spoken_text": " Second thought.",
                "seed": 7,
                "run_on": {"spoken_text": " Next words.", "cut_sample": 48000},
            },
        ]
        second = dying(48000) if natural else np.full(48000, 2000, dtype=np.int16)
        record, settings = retained_record(
            tmp_path, plans, [np.full(48000, 1000, dtype=np.int16), second]
        )
        return tmp_path, record, plans, settings

    return build
