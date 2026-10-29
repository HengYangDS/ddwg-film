"""How a take begins and ends: heard quiet at its start, and a natural, decaying end."""

import numpy as np

import filmkit.narration.take_edges as narration_take_edges

RATE = 24000


def voiced(seconds: float) -> np.ndarray:
    t = np.arange(round(seconds * RATE)) / RATE
    return 0.3 * np.sin(2 * np.pi * 150 * t) + 0.1 * np.sin(2 * np.pi * 300 * t)


def pcm(signal: np.ndarray) -> np.ndarray:
    return np.round(signal * 32767).astype("<i2")


def test_ending_tells_a_decaying_tail_from_an_abrupt_cut():
    silence = np.zeros(round(0.1 * RATE))
    envelope = np.ones(round(1.25 * RATE))
    envelope[-round(0.25 * RATE) :] = np.exp(-np.arange(round(0.25 * RATE)) / 480)
    decaying = narration_take_edges.ending(
        pcm(np.concatenate([voiced(1.25) * envelope, silence])), RATE
    )
    assert decaying["decays"]
    assert decaying["natural"]
    assert decaying["final_dbfs"] <= -55
    assert decaying["seconds"] == 1.35
    # Digital silence after a cut hides it from the level checks, not from the decay.
    cut = narration_take_edges.ending(pcm(np.concatenate([voiced(1.25), silence])), RATE)
    assert cut["last30_rms"] == 0
    assert cut["end_ratio"] == 0
    assert cut["tail_voicing"] >= 0.6
    assert cut["final_dbfs"] > -55
    assert not cut["decays"]
    assert not cut["natural"]
    unpadded = narration_take_edges.ending(pcm(voiced(1.25)), RATE)
    assert unpadded["end_ratio"] > 0.9
    assert not unpadded["natural"]
    # An unvoiced final cut while still heard passes the level checks, but its last
    # 10 ms lie above -55 dBFS.
    hiss = 0.0056 * np.random.default_rng(7).standard_normal(round(0.3 * RATE))
    fricative = narration_take_edges.ending(pcm(np.concatenate([voiced(0.3), hiss])), RATE)
    assert fricative["final_dbfs"] > -55
    assert not fricative["natural"]


def stop(fall_ms: float) -> np.ndarray:
    """A voiced syllable at -30 dBFS that stops over `fall_ms`, then quiet noise and zeros."""
    hold = voiced(0.6) * 10 ** (-30 / 20) / 0.22
    ramp = round(fall_ms * RATE / 1000)
    hold[-ramp:] *= np.linspace(1, 0, ramp) ** 3
    noise = 10 ** (-80 / 20) * np.random.default_rng(3).standard_normal(round(0.08 * RATE))
    return pcm(np.concatenate([np.zeros(240), hold, noise, np.zeros(round(0.03 * RATE))]))


def test_ending_refuses_a_voiced_syllable_that_stops_within_a_few_milliseconds():
    # A voiced final that falls from -40 to -65 dBFS in under 6 ms stops inside the
    # syllable, even when the noise after it satisfies the decay checks.
    stopped = narration_take_edges.ending(stop(2), RATE)
    assert stopped["final_fall_ms"] < narration_take_edges.FALL_MS
    assert stopped["final_voicing"] >= narration_take_edges.FALL_VOICING
    assert stopped["final_dbfs"] <= -55
    assert not stopped["natural"]
    dying = narration_take_edges.ending(stop(40), RATE)
    assert dying["final_fall_ms"] >= narration_take_edges.FALL_MS
    assert dying["natural"]


def test_the_fall_does_not_depend_on_where_the_take_starts_on_the_frame_grid():
    # The same take placed a few samples later lands on another phase of the 1 ms grid.
    falls = {
        narration_take_edges.final_fall(np.concatenate([np.zeros(k, "<i2"), stop(4)]), RATE)[
            "final_fall_ms"
        ]
        for k in range(RATE // 1000)
    }
    assert len(falls) == 1


def tone(seconds: float, dbfs: float) -> np.ndarray:
    """A steady voice at `dbfs`.

    Its 1 kHz and 2 kHz partials fill each 1 ms frame with whole periods, so each frame's level
    holds steady.
    """
    t = np.arange(round(seconds * RATE)) / RATE
    wave_form = 0.3 * np.sin(2 * np.pi * 1000 * t) + 0.1 * np.sin(2 * np.pi * 2000 * t)
    return wave_form * 10 ** (dbfs / 20) / np.sqrt(0.05)


def faded_then_cut(floor_dbfs: float) -> np.ndarray:
    """A syllable at -30 dBFS that fades to `floor_dbfs` and is then cut.

    It fades over 32 ms, holds 10 ms and stops within 2 ms, followed by quiet noise and zeros.
    """
    fade = round(0.032 * RATE)
    held = np.concatenate([tone(0.5, -30), tone(0.01, floor_dbfs)])
    held[-fade - round(0.01 * RATE) : -round(0.01 * RATE)] = tone(0.032, 0) * 10 ** (
        np.linspace(-30, floor_dbfs, fade) / 20
    )
    held[-round(0.002 * RATE) :] *= np.linspace(1, 0, round(0.002 * RATE)) ** 3
    noise = 10 ** (-80 / 20) * np.random.default_rng(5).standard_normal(round(0.08 * RATE))
    return pcm(np.concatenate([np.zeros(240), held, noise, np.zeros(round(0.03 * RATE))]))


def test_a_voice_cut_below_the_takes_own_bounds_is_judged_where_the_gain_lifts_it():
    # Fading to -45.5 dBFS before the cut, the voice crosses -40 dBFS 13 ms or more before it
    # stops; the soundtrack raises it by up to FALL_GAIN_DB, where the same cut stops at once.
    cut = narration_take_edges.ending(faded_then_cut(-45.5), RATE)
    assert cut["final_fall_ms"] < narration_take_edges.FALL_MS
    assert cut["final_voicing"] >= narration_take_edges.FALL_VOICING
    assert cut["decays"]
    assert not cut["natural"]
    # Cut 30 dB lower, no gain the soundtrack applies brings the voice near the bounds.
    assert narration_take_edges.ending(faded_then_cut(-60), RATE)["natural"]
    # A delivered take is judged at the gain it was delivered with: lifted 4.5 dB, the cut voice
    # still crosses -40 dBFS 13 ms before it stops.
    assert narration_take_edges.ending(faded_then_cut(-45.5), RATE, gains=(0, 4.5))["natural"]


def test_phrase_ends_are_judged_where_heard_quiet_follows_them():
    quiet = 10 ** (-80 / 20) * np.random.default_rng(9).standard_normal(round(0.15 * RATE))
    cut = tone(0.4, -25)
    cut[-round(0.002 * RATE) :] *= np.linspace(1, 0, round(0.002 * RATE)) ** 3
    dying = tone(0.4, -25)
    dying[-round(0.2 * RATE) :] *= np.exp(-np.arange(round(0.2 * RATE)) / (0.02 * RATE))
    head = np.zeros(240)
    take = pcm(np.concatenate([head, cut, quiet, dying, quiet, tone(0.4, -25), quiet]))
    first = len(head) + len(cut)
    second = first + len(quiet) + len(dying)
    heard = narration_take_edges.phrase_ends(take, RATE, [first, second])
    assert [end["end_sample"] for end in heard] == [first, second]
    assert [end["stops"] for end in heard] == [True, False]
    assert heard[0]["final_fall_ms"] < narration_take_edges.FALL_MS
    # A phrase end that runs on into the next words without heard quiet is not judged.
    assert narration_take_edges.phrase_ends(take, RATE, [round(0.2 * RATE)]) == []


def test_opening_tells_a_take_that_begins_in_quiet_from_one_heard_at_once():
    begins_quiet = narration_take_edges.opening(
        pcm(np.concatenate([np.zeros(480), voiced(0.5)])), RATE
    )
    assert begins_quiet["opens_quiet"]
    assert begins_quiet["first_dbfs"] <= -55
    heard_at_once = narration_take_edges.opening(pcm(voiced(0.5)), RATE)
    assert not heard_at_once["opens_quiet"]
    assert heard_at_once["first_dbfs"] > -55
