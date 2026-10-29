"""The verifier's narration custody and caption contract."""

import json

import pytest

import ddwg_film.delivery.verification as delivery_verification
import ddwg_film.repository as repository
from ddwg_film.delivery.verification import VerificationError


def cue(start: float, end: float, text: str = "数据先行。", **extra) -> dict:
    return {"start": start, "end": end, "text": text, **extra}


# The short films' captions must end by their credits at one second.
@pytest.mark.parametrize(
    "captions",
    [
        [cue(-0.1, 0.5)],
        [cue(0.5, 0.5)],
        [cue(0.5, 1.01)],
        [cue(0.0, 0.6), cue(0.4, 0.8)],
        [cue(0.0, 0.5, "数据\n先行。")],
        [cue(0.0, 0.5, "数" * 34)],
        [cue(0.0, 0.5, display_text="交付先行。")],
        [cue(0.0, 0.5, display_text="数据\n先行。")],
    ],
    ids=[
        "before-start",
        "empty",
        "into-credits",
        "overlap",
        "two-lines",
        "too-long",
        "other-words",
        "display-two-lines",
    ],
)
@pytest.mark.usefixtures("short_films")
def test_captions_outside_the_caption_contract_are_refused(captions):
    with pytest.raises(VerificationError, match="caption contract"):
        delivery_verification.verify_captions({"captions": captions}, "zh")


@pytest.mark.usefixtures("short_films")
def test_single_line_captions_within_their_limit_and_before_the_credits_pass():
    captions = [cue(0.0, 0.5, "数" * 33), cue(0.35, 1.0, display_text="数据，先行。")]
    assert delivery_verification.verify_captions({"captions": captions}, "zh") == 2


def test_current_narration_passes_and_validates_every_selected_recording(inputs):
    edition = inputs.edition
    assert delivery_verification.verify_narration(edition) == {
        "segments": 2,
        "captions": 2,
        "soundtrack_sha256": repository.sha(edition.soundtrack),
        "program_level": {"integrated_lufs": -16.6, "true_peak_dbtp": -1.2},
    }
    cast = json.loads((inputs.root / edition.cast).read_text())
    assert inputs.checked == [
        ("groups", "01", inputs.root),
        ("voice", "01", cast),
        ("groups", "02", inputs.root),
        ("voice", "02", cast),
    ]


def mirror_differs(inputs):
    (inputs.root / inputs.edition.mirror).write_text("数据先行。\n")


def recording_changed(inputs):
    (inputs.edition.ear_first / "recordings/02.wav").write_text("another take")


def selected(*keys, value):
    return lambda inputs: inputs.change(inputs.edition.narration_selected, *keys, value=value)


def assembly(*keys, value):
    return lambda inputs: inputs.change(inputs.edition.audio_assembly, *keys, value=value)


def timeline(*keys, value):
    return lambda inputs: inputs.change(inputs.edition.timeline, *keys, value=value)


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (mirror_differs, "Narration mirror differs"),
        (selected("script_sha256", value="0"), "custody"),
        (selected("cast_sha256", value="0"), "custody"),
        (assembly("script_sha256", value="0"), "custody"),
        (assembly("soundtrack_sha256", value="0"), "custody"),
        (lambda inputs: inputs.soundtrack(2 * 44100, rate=44100), "exact 48 kHz stereo"),
        (lambda inputs: inputs.soundtrack(2 * 48000, channels=1), "exact 48 kHz stereo"),
        (lambda inputs: inputs.soundtrack(3 * 48000), "exact 48 kHz stereo"),
        (assembly("program_level", "policy", value={}), "declared program level"),
        (
            assembly("program_level", "after", "integrated_lufs", value=-17.1),
            "declared program level",
        ),
        (assembly("program_level", "after", "true_peak_dbtp", value=-0.9), "program level"),
        (assembly("program_level", value={}), "declared program level"),
        (timeline("segments", "1", "id", value="03"), "differ in segment order"),
        (selected("records", "1", "id", value="03"), "differ in segment order"),
        (selected("records", "1", "text", value="交付。"), "Selected recording differs: 02"),
        (recording_changed, "Selected recording differs: 02"),
        (timeline("captions", "1", "end", value=2), "caption contract"),
    ],
)
def test_narration_custody_refusals(inputs, damage, message):
    damage(inputs)
    with pytest.raises(VerificationError, match=message):
        delivery_verification.verify_narration(inputs.edition)
