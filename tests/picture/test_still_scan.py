"""Exercise the still-picture scan on small grey frames and a timeline."""

import hashlib
import json
import subprocess

import numpy as np
import pytest

import filmkit.picture.still_scan as still_scan
import filmkit.repository as repository


def timeline(*spans):
    words = [{"text": f"w{k}", "start": a, "end": b} for k, (a, b) in enumerate(spans)]
    return {"segments": [{"id": "01", "words": words}]}


def frames(moving, still, *, toggle=0):
    """A bright square that moves for `moving` frames and then stands for `still` more."""
    out = []
    for k in range(moving + still):
        frame = np.full((still_scan.HEIGHT, still_scan.WIDTH), 15, dtype=np.uint8)
        x = 100 + 5 * min(k, moving - 1)
        frame[100:120, x : x + 20] = 200
        if toggle and k % 2:
            frame[60 : 60 + toggle, 60:61] = 200
        out.append(frame)
    return out


def test_a_still_run_carries_the_speech_inside_it():
    report = still_scan.scan(frames(10, 30), timeline((1.5, 2.5), (2.6, 3.5)))
    assert report["fine"]["runs"] == [{"start": 0.9, "end": 3.9, "speech": 1.9}]
    assert report["longest_fine_speech"] == 1.9


def test_a_change_of_a_few_pixels_leaves_the_picture_still():
    report = still_scan.scan(frames(10, 30, toggle=4), timeline((1.0, 3.8)))
    assert report["fine"]["runs"] == [{"start": 0.9, "end": 3.9, "speech": 2.8}]


def test_moving_marks_carry_no_still_run():
    report = still_scan.scan(frames(40, 0), timeline((0.5, 3.5)))
    assert report["fine"]["runs"] == []
    assert report["coarse"]["runs"] == []
    assert report["longest_fine_speech"] == 0


def test_the_coarse_measure_compares_frames_two_steps_apart():
    # A change of 30 pixels in every other frame is motion to the fine measure only.
    report = still_scan.scan(frames(10, 30, toggle=30), timeline((1.0, 3.8)))
    assert report["fine"]["runs"] == []
    assert report["coarse"]["runs"] == [{"start": 1.0, "end": 3.8, "speech": 2.8}]


def test_the_limit_fails_a_run_that_carries_too_much_speech():
    report = still_scan.scan(frames(10, 30), timeline((0.9, 3.9)))
    assert still_scan.over_limit(report, 3.0) == [{"start": 0.9, "end": 3.9, "speech": 3.0}]
    assert still_scan.over_limit(report, 3.5) == []


def test_the_worse_of_two_sampling_phases_decides():
    # A run that one phase sees moving at its edge is still on the other, offset 0.05 s.
    early = still_scan.scan(frames(10, 30), timeline((0.9, 3.9)))
    late = still_scan.scan(frames(12, 28), timeline((0.9, 3.9)))
    both = still_scan.worst([late, early])
    assert both["longest_fine_speech"] == early["longest_fine_speech"] == 3.0
    assert both["fine"]["runs"] == early["fine"]["runs"]
    assert both["phases"] == 2


def test_a_scan_of_no_frames_is_refused():
    # A scan that read no frames has not judged the film, so it never passes it.
    with pytest.raises(still_scan.StillScanError, match="no frames"):
        still_scan.scan([], timeline((0.5, 1.0)))


@pytest.mark.ffmpeg
def test_a_film_that_cannot_be_read_is_refused(tmp_path):
    with pytest.raises(still_scan.StillScanError, match="no frames"):
        list(still_scan.decode(tmp_path / "absent.mp4"))


@pytest.mark.ffmpeg
@pytest.mark.parametrize("rate", [10, 60])
def test_each_phase_reads_ten_frames_a_second_at_any_frame_rate(tmp_path, rate):
    # A draft is rendered at 10 fps and a final film at 60 fps; both read 10 frames per second.
    movie = tmp_path / f"grey-{rate}.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=gray:size=480x270:rate={rate}:duration=2",
            "-pix_fmt",
            "yuv420p",
            str(movie),
        ],
        check=True,
    )
    assert len(list(still_scan.decode(movie, 0))) == 20
    assert len(list(still_scan.decode(movie, 1))) == 20


def test_the_scan_record_names_the_film_and_timeline_it_judged(tmp_path, monkeypatch):
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    (tmp_path / "film.mp4").write_bytes(b"a rendered film")
    repository.write("timeline.json", timeline((1.0, 1.5)))
    monkeypatch.setattr(still_scan, "decode", lambda _movie, _phase: iter(frames(40, 0)))
    still_scan.main(["film.mp4", "timeline.json", "--out", "scan.json"])
    record = json.loads((tmp_path / "scan.json").read_text())
    assert record["movie"] == {
        "path": "film.mp4",
        "sha256": hashlib.sha256(b"a rendered film").hexdigest(),
    }
    assert record["timeline"]["path"] == "timeline.json"
    assert record["timeline"]["sha256"] == repository.sha(tmp_path / "timeline.json")
