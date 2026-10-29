"""Media probes, frame cadence and complete decodes through FFmpeg."""

import subprocess

import pytest
from PIL import Image

import ddwg_film.media as media


@pytest.mark.ffmpeg
def test_mixed_time_base_splice_requires_native_cadence(tmp_path):
    first, second = tmp_path / "first.mp4", tmp_path / "second.mp4"
    for target, scale, color in [(first, 90000, "black"), (second, 15360, "white")]:
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-f",
                "lavfi",
                "-i",
                f"color={color}:s=64x36:r=60",
                "-frames:v",
                "60",
                "-c:v",
                "libx264",
                "-bf",
                "0",
                "-video_track_timescale",
                str(scale),
                str(target),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    manifest = tmp_path / "segments.txt"
    manifest.write_text(f"file '{first}'\nfile '{second}'\n")
    bad = tmp_path / "bad.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-c",
            "copy",
            str(bad),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with pytest.raises(media.MediaError, match=r"cadence|duration"):
        media.video_cadence(bad, 120, 60)
    normalized = tmp_path / "normalized.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(second),
            "-c",
            "copy",
            "-video_track_timescale",
            "90000",
            str(normalized),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    manifest.write_text(f"file '{first}'\nfile '{normalized}'\n")
    good = tmp_path / "good.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-c",
            "copy",
            str(good),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    assert media.video_cadence(good, 120, 60)["every_frame_checked"]


def test_long_film_decode_finishes_and_rejects_partial_or_corrupt_results(
    tmp_path,
    monkeypatch,
):
    """Keep complete decode mandatory when its runtime exceeds the old limit."""
    movie = tmp_path / "current-film.mp4"
    outputs = [
        (0, b"frame=36000\nprogress=continue\nframe=72000\nprogress=end\n", b""),
        (0, b"frame=71999\nprogress=end\n", b""),
        (0, b"frame=72000\nprogress=end\n", b"decode error"),
        (1, b"frame=72000\nprogress=end\n", b""),
    ]

    def slower_complete_decode(command, *, timeout, **kwargs):
        assert command[command.index("-i") + 1] == str(movie)
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert "-hwaccel" not in command
        assert "-t" not in command
        assert "-map" in command
        assert "0:a:0" in command
        if timeout < 620:
            raise subprocess.TimeoutExpired(command, timeout)
        return subprocess.CompletedProcess(command, *outputs.pop(0))

    monkeypatch.setattr(media.subprocess, "run", slower_complete_decode)
    assert media.decoded_video_frames(movie, 72000, 1200) == 72000
    for _ in range(3):
        with pytest.raises(media.MediaError):
            media.decoded_video_frames(movie, 72000, 1200)
    assert not outputs


@pytest.mark.ffmpeg
def test_native_probe_reads_complete_packaged_subject(tmp_path):
    movie = tmp_path / "probe-subject.mp4"
    video = tmp_path / "probe-video.mp4"
    cover = tmp_path / "cover.png"
    Image.new("RGB", (160, 90), "#10151a").save(cover)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x10151a:s=160x90:r=60:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v:0",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-t",
            "1",
            str(video),
        ],
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=30,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(video),
            "-i",
            str(cover),
            "-map",
            "0",
            "-map",
            "1:v:0",
            "-c",
            "copy",
            "-c:v:1",
            "mjpeg",
            "-disposition:v:1",
            "attached_pic",
            str(movie),
        ],
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=30,
    )
    data = media.probe(movie)
    assert float(data["format"]["duration"]) == 1
    assert any(s.get("disposition", {}).get("attached_pic") for s in data["streams"])


def probed(**video):
    """A probe result: a cover picture before the film's video stream, as packaging writes."""
    stream = {
        "codec_type": "video",
        "nb_frames": "120",
        "avg_frame_rate": "60/1",
        "width": 64,
        "height": 36,
        "duration": "2.000000",
    }
    cover = {"codec_type": "video", "disposition": {"attached_pic": 1}}
    return {"streams": [cover, stream | video], "format": {"duration": "2.000000"}}


def test_the_video_contract_reads_the_film_stream_not_the_cover():
    contract = {"frames": 120, "fps": 60, "size": (64, 36), "duration": 2}
    assert media.require_video(probed(), **contract)["nb_frames"] == "120"
    for change, field in [
        ({"nb_frames": "119"}, "frame count"),
        ({"avg_frame_rate": "30/1"}, "frame rate"),
        ({"width": 32}, "frame size"),
        ({"duration": "2.100000"}, "stream duration"),
        ({"duration": None}, "stream duration"),
    ]:
        with pytest.raises(media.MediaError, match=field):
            media.require_video(probed(**change), **contract)
    with pytest.raises(media.MediaError, match="no video stream besides a cover picture"):
        media.video_stream({"streams": probed()["streams"][:1]})
