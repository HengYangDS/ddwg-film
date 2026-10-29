"""How a take begins and ends: its opening level, its final syllable's decay and its ending.

A take that opens its recording must begin in heard quiet, and every take must end
naturally: quiet at its end, with a final syllable that dies away rather than being cut.
"""

from __future__ import annotations

import numpy as np

from ddwg_film.soundtrack.quiet import HEARD_QUIET_DBFS

# A voiced final syllable that falls from LOUD_DBFS to STOPPED_DBFS in under FALL_MS stops
# inside the syllable instead of dying away; round-21 takes that a listener heard cut fell in
# 2-4 ms, against a median of 22 ms over every ending. The fall is the median over every
# sample phase of the 1 ms frame grid, so it does not depend on where a take starts. It is
# judged on the take's own scale and with both bounds lowered by each whole decibel of gain
# up to FALL_GAIN_DB, which covers the program gain with the thought and chapter leveling
# (2.7-5.4 dB in round 23): a voice that fades below LOUD_DBFS before it is cut is heard
# louder in the soundtrack, where the same cut stops at once.
FALL_MS = 6
FALL_VOICING = 0.8
FALL_GAIN_DB = 6
# The gains a take is judged at before its gain in the soundtrack is known.
FALL_GAINS = tuple(range(FALL_GAIN_DB + 1))
LOUD_DBFS, STOPPED_DBFS = -40.0, -65.0
# A phrase end inside a take is heard where the aligned end of its last unit lies in a run of
# at least this much heard quiet, or where such a run begins within PHRASE_REACH_SECONDS after it.
PHRASE_QUIET_SECONDS = 0.08
PHRASE_REACH_SECONDS = 0.1


def voicing(x: np.ndarray, rate: int) -> float:
    """Peak normalized cross-correlation of a window with itself lagged by 90-400 Hz periods."""
    x = x - x.mean() if len(x) else x
    best = 0.0
    for lag in range(rate // 400, min(rate // 90, len(x) - 1)):
        a, b = x[:-lag], x[lag:]
        best = max(best, float(np.dot(a, b) / (np.sqrt(np.dot(a, a) * np.dot(b, b)) + 1e-20)))
    return best


def final_fall(pcm: np.ndarray, rate: int, gains: tuple[float, ...] = FALL_GAINS) -> dict:
    """How fast a take's last loud syllable falls silent, and how voiced it was before.

    On 1 ms RMS frames the fall runs from the last frame at or above LOUD_DBFS to the first
    later frame at or below STOPPED_DBFS. It is the median over every sample phase of the
    frame grid, taken with both bounds lowered by each of `gains` in decibels, and the
    shortest of these is reported with the gain that gives it. The voicing is that of the
    15 ms before the fall on the take's own scale.
    """
    x = pcm.astype(np.float64) / 32768
    ms = rate // 1000
    grids = []
    for phase in range(ms):
        frames = (len(x) - phase) // ms
        shifted = x[phase : phase + frames * ms].reshape(-1, ms)
        grids.append(20 * np.log10(np.sqrt(np.mean(shifted**2, axis=1)) + 1e-12))
    fall, gain = None, 0
    for lowered in gains:
        falls = []
        for levels in grids:
            loud = np.flatnonzero(levels >= LOUD_DBFS - lowered)
            if len(loud):
                last = int(loud[-1])
                stopped = np.flatnonzero(levels[last:] <= STOPPED_DBFS - lowered)
                falls.append(int(stopped[0]) if len(stopped) else len(levels) - last)
        if falls and (fall is None or float(np.median(falls)) < fall):
            fall, gain = float(np.median(falls)), lowered
    loud = np.flatnonzero(grids[0] >= LOUD_DBFS)
    if fall is None or not len(loud):
        return {"final_fall_ms": fall, "final_fall_gain_db": gain, "final_voicing": 0.0}
    end = (int(loud[-1]) + 1) * ms
    return {
        "final_fall_ms": fall,
        "final_fall_gain_db": gain,
        "final_voicing": round(voicing(x[max(0, end - 15 * ms) : end], rate), 2),
    }


def phrase_ends(
    pcm: np.ndarray, rate: int, ends: list[int], gains: tuple[float, ...] = FALL_GAINS
) -> list[dict]:
    """How the heard phrase ends of a mono 16-bit take fall silent.

    `ends` are the samples where aligned phrase-final units end. A phrase end is heard where it
    lies in a run of at least PHRASE_QUIET_SECONDS of 10 ms frames at or below HEARD_QUIET_DBFS,
    or where such a run begins within PHRASE_REACH_SECONDS after it, and its last syllable is
    judged by `final_fall` at `gains` over the take up to that run's end: it stops when it is
    voiced and falls in under FALL_MS.
    """
    x = pcm.astype(np.float64) / 32768
    frame = round(0.01 * rate)
    levels = 20 * np.log10(
        np.sqrt(np.mean(x[: len(x) // frame * frame].reshape(-1, frame) ** 2, axis=1)) + 1e-12
    )
    edges = np.diff(np.concatenate([[0], (levels <= HEARD_QUIET_DBFS).astype(int), [0]]))
    runs = [
        (start * frame, stop * frame)
        for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True)
        if (stop - start) * frame >= round(PHRASE_QUIET_SECONDS * rate)
    ]
    heard = []
    for end in ends:
        reach = round(PHRASE_REACH_SECONDS * rate)
        run = next((r for r in runs if r[0] - reach <= end <= r[1]), None)
        if run is None:
            continue
        fall = final_fall(pcm[max(0, run[0] - round(0.3 * rate)) : run[1]], rate, gains)
        stops = (
            fall["final_fall_ms"] is not None
            and fall["final_fall_ms"] < FALL_MS
            and fall["final_voicing"] >= FALL_VOICING
        )
        heard.append({"end_sample": end, **fall, "stops": stops})
    return heard


def decay(pcm: np.ndarray, rate: int) -> dict:
    """Whether a take's final syllable dies away instead of meeting the join voiced.

    The take ends at its last nonzero sample. The 20 ms ending 10 ms before it must be
    unvoiced (normalized autocorrelation below 0.6 at 90-400 Hz over the 40 ms before
    it) or at least 15 dB below the take's speech median (10 ms RMS frames above
    -40 dBFS), so the quiet that follows never begins on voicing. The last 10 ms must
    also lie at or below -55 dBFS, the production's heard quiet before the program
    gain, so an unvoiced final such as a fricative has died away rather than been cut.
    """
    x = pcm.astype(np.float64) / 32768
    sounded = np.flatnonzero(pcm)
    end = int(sounded[-1]) + 1 if len(sounded) else len(pcm)
    frame = round(0.01 * rate)
    frames = 20 * np.log10(
        np.sqrt(np.mean(x[: len(x) // frame * frame].reshape(-1, frame) ** 2, axis=1)) + 1e-12
    )
    speech = float(np.median(frames[frames > -40])) if np.any(frames > -40) else -40.0
    window = x[max(0, end - round(0.03 * rate)) : max(0, end - round(0.01 * rate))]
    drop = 20 * np.log10(np.sqrt(np.mean(window**2)) + 1e-12) - speech if len(window) else -99.0
    part = x[max(0, end - round(0.05 * rate)) : max(0, end - round(0.01 * rate))]
    part = part - part.mean() if len(part) else part
    voiced = 0.0
    if len(part) and np.sqrt(np.mean(part**2)) >= 10 ** (-45 / 20):
        corr = np.correlate(part, part, "full")[len(part) - 1 :]
        corr = corr / (corr[0] + 1e-12)
        low, high = rate // 400, rate // 90
        voiced = float(corr[low:high].max()) if high < len(corr) else 0.0
    last = x[max(0, end - round(0.01 * rate)) : end]
    final = float(20 * np.log10(np.sqrt(np.mean(last**2)) + 1e-12)) if len(last) else -120.0
    return {
        "tail_drop_db": round(float(drop), 1),
        "tail_voicing": round(voiced, 2),
        "final_dbfs": round(final, 1),
        "decays": bool((voiced < 0.6 or drop <= -15) and final <= -55),
    }


def ending(pcm: np.ndarray, rate: int, gains: tuple[float, ...] = FALL_GAINS) -> dict:
    """Ending metrics of a mono 16-bit take and whether it ends naturally.

    end_ratio is the final 10 ms level over the loudest 10 ms of the last 300 ms, and
    last30_rms the RMS of the final 30 ms. A take ends naturally when its final 30 ms
    are quiet (RMS at most 0.01, or at most 0.02 with an end ratio at most 0.12), its
    final syllable decays, and that syllable, if voiced, does not stop within FALL_MS at any
    of `gains`.
    """
    window = round(0.01 * rate)
    tail = pcm[-round(0.3 * rate) :].astype(np.float64) / 32768
    levels = np.sqrt(np.mean(tail[: len(tail) // window * window].reshape(-1, window) ** 2, axis=1))
    last = float(np.sqrt(np.mean((pcm[-round(0.03 * rate) :].astype(np.float64) / 32768) ** 2)))
    ratio = float(levels[-1] / max(levels.max(), 1e-6))
    tail_decay = decay(pcm, rate)
    fall = final_fall(pcm, rate, gains)
    quiet = last <= 0.01 or (last <= 0.02 and ratio <= 0.12)
    stops = fall["final_fall_ms"] is not None and fall["final_fall_ms"] < FALL_MS
    return {
        "end_ratio": round(ratio, 3),
        "last30_rms": round(last, 4),
        "seconds": round(len(pcm) / rate, 3),
        **tail_decay,
        **fall,
        "natural": bool(
            quiet and tail_decay["decays"] and not (stops and fall["final_voicing"] >= FALL_VOICING)
        ),
    }


def opening(pcm: np.ndarray, rate: int) -> dict:
    """The level of a mono 16-bit take's first 10 ms and whether it is heard as quiet.

    A take that opens its recording begins its clip, which starts in the take's own
    quiet, so a take heard from its first sample would step out of digital silence.
    """
    head = pcm[: round(0.01 * rate)].astype(np.float64) / 32768
    level = float(20 * np.log10(np.sqrt(np.mean(head**2)) + 1e-12))
    return {"first_dbfs": round(level, 1), "opens_quiet": level <= HEARD_QUIET_DBFS}
