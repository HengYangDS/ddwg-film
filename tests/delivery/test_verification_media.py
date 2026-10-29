"""The verifier's complete decode of a delivered film against its delivery contract."""

import pytest

import filmkit.delivery.packaging as delivery_packaging
import filmkit.delivery.verification as delivery_verification
import filmkit.media as media
import filmkit.production as production
import filmkit.repository as repository
import filmkit.specification as specification
from filmkit.delivery.verification import VerificationError

FRAMES = specification.DURATION * specification.FPS
SAMPLE_FRAMES = specification.DURATION * specification.RATE


def probe(changes: dict) -> dict:
    """A probe of a delivered UHD film that meets the delivery contract, with changes.

    Each change names its field by keys and list indices joined by slashes; None removes it.
    """
    seconds = f"{specification.DURATION:.6f}"
    language = specification.ISO_LANGUAGES["zh"]
    video = {
        "codec_type": "video",
        "avg_frame_rate": "60/1",
        "nb_frames": str(FRAMES),
        "duration": seconds,
        "field_order": "progressive",
        "color_primaries": "bt709",
        "color_transfer": "bt709",
        "color_space": "bt709",
        "width": 3840,
        "height": 2160,
        "level": specification.H264_LEVELS[2160],
        "tags": {"language": language, "handler_name": "画面"},
    }
    audio = {
        "codec_type": "audio",
        "sample_rate": str(specification.RATE),
        "channels": 2,
        "duration": seconds,
        "tags": {"language": language, "handler_name": "中文旁白"},
    }
    release = delivery_packaging.delivered_tags(
        production.Edition("zh"), production.RENDITIONS["uhd"]
    )
    data = {
        "streams": [video, audio, {"codec_type": "video", "disposition": {"attached_pic": 1}}],
        "format": {"duration": seconds, "tags": {**release, "author": specification.AUTHOR}},
        "chapters": [{}] * delivery_packaging.CHAPTERS,
    }
    for keys, value in changes.items():
        place = data
        *path, last = keys.split("/")
        for key in path:
            place = place[int(key)] if key.isdigit() else place[key]
        if value is None:
            del place[last]
        else:
            place[last] = value
    return data


@pytest.fixture
def decoded(tmp_path, monkeypatch):
    """A delivered UHD film whose decodes succeed, and a check of it under a changed probe."""
    script = repository.read(production.Edition("zh").script)
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    repository.write(
        production.Edition("zh").script, {"title": script["title"], "release": script["release"]}
    )
    film = production.Edition("zh").film("uhd")
    film.parent.mkdir(parents=True)
    film.write_text("film\n")
    monkeypatch.setattr(media, "video_cadence", lambda *_: {})
    monkeypatch.setattr(media, "decoded_video_frames", lambda *_: FRAMES)
    monkeypatch.setattr(media, "decoded_audio_frames", lambda _path: SAMPLE_FRAMES)

    def check(changes=None):
        monkeypatch.setattr(media, "probe", lambda _path: probe(changes or {}))
        return delivery_verification.verify_media(production.Edition("zh"), film, (3840, 2160))

    return film, check


def test_a_delivered_film_meeting_its_contract_is_decoded_completely(decoded):
    film, check = decoded
    assert check() == {
        "path": "build/artifacts/film/zh/ddwg-zh-uhd.mp4",
        "sha256": repository.sha(film),
        "bytes": film.stat().st_size,
        "dimensions": [3840, 2160],
        "video_frames": FRAMES,
        "audio_sample_frames_decoded": SAMPLE_FRAMES,
    }
    # The QuickTime author tag stands in for the author tag, and an unknown field order passes.
    quicktime = {
        "format/tags/author": None,
        "format/tags/com.apple.quicktime.author": specification.AUTHOR,
        "streams/0/field_order": "unknown",
    }
    assert check(quicktime)["video_frames"] == FRAMES


@pytest.mark.parametrize(
    "changes",
    [
        {"streams/0/avg_frame_rate": "30/1"},
        {"streams/0/nb_frames": "89999"},
        {"streams/0/duration": "1499.900000"},
        {"format/duration": "1500.100000"},
        {"streams/0/field_order": "tt"},
        {"streams/0/color_primaries": "bt2020"},
        {"streams/0/color_transfer": None},
        {"streams/0/color_space": "smpte170m"},
        {"streams/0/width": 1920},
        {"streams/0/level": 51},
        {"streams/1/sample_rate": "44100"},
        {"streams/1/channels": 1},
        {"streams/1/duration": "1499.000000"},
        {"streams/2/disposition": {}},
        {"format/tags/artist": "Someone else"},
        {"format/tags/author": "Someone else"},
        {"format/tags/genre": None},
        {"format/tags/com.apple.quicktime.title": "Another film"},
        {"format/tags/hd_video": "2"},
        {"streams/0/tags": {"language": "zho", "handler_name": "VideoHandler"}},
        {"streams/0/tags": {"language": "eng"}},
        {"streams/1/tags": {}},
        {"chapters": []},
        {"streams/1/codec_type": "data"},
    ],
    ids=",".join,
)
def test_a_delivered_film_outside_its_contract_is_refused(decoded, changes):
    film, check = decoded
    with pytest.raises(VerificationError, match=f"delivery contract: {film.name}"):
        check(changes)


def test_a_decoded_soundtrack_of_another_length_is_refused(decoded, monkeypatch):
    film, check = decoded
    monkeypatch.setattr(media, "decoded_audio_frames", lambda _path: SAMPLE_FRAMES + 1025)
    with pytest.raises(VerificationError, match=f"Decoded audio length differs: {film.name}"):
        check()
    # AAC encoder padding up to one frame of 1024 samples is distinct from the sample domain.
    monkeypatch.setattr(media, "decoded_audio_frames", lambda _path: SAMPLE_FRAMES + 1024)
    assert check()["audio_sample_frames_decoded"] == SAMPLE_FRAMES + 1024


def test_a_film_with_only_a_cover_picture_is_refused(decoded):
    _, check = decoded
    with pytest.raises(VerificationError, match="no video stream besides a cover picture"):
        check({"streams/0/codec_type": "data"})
