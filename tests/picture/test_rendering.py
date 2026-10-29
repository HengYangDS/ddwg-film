"""Stage, render and bind the picture with fixture inputs and the real composition."""

import contextlib
import json
import os
import re
import shutil
import signal
import sys
import textwrap
import time
from pathlib import Path

import pytest

import ddwg_film.media as media
import ddwg_film.picture.rendering as picture_rendering
import ddwg_film.repository as repository
from ddwg_film.picture.rendering import PictureError
from ddwg_film.production import Edition
from ddwg_film.specification import DURATION, FPS

# The real composition, found before a test rebinds the repository root.
COMPOSITION = Path(picture_rendering.__file__).with_name("composition")
# The template patterns that the renderer document replaces.
PLACEHOLDERS = (
    "/* FILM_DATA */",
    '<link rel="stylesheet" href="film.css">',
    '<script src="film.js"></script>',
    'data-duration="1200"',
    'data-width="1920"',
    'data-height="1080"',
    'content="width=1920, height=1080"',
    'width="1920" height="1080"',
)
RECEIPT_KEYS = [
    "command",
    "exit",
    "timed_out",
    "deadline_seconds",
    "started_at",
    "elapsed_seconds",
    "source_sha256",
    "output_path",
    "output_sha256",
]


def put(path, data):
    """Write text or JSON to a fixture file, creating its folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))
    return path


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    """A repository root with both editions' current inputs and the real composition."""
    root = tmp_path.resolve()
    monkeypatch.setattr(repository, "ROOT", root)
    shutil.copytree(COMPOSITION, root / picture_rendering.COMPOSITION)
    for path, source in picture_rendering.STAGED_MEMBERS:
        if not (root / source).exists():
            put(root / source, f"fixture {path}")
    put(root / "content/source-manifest.json", {"members": []})
    for code, text in (("zh", "先看数据。"), ("en", "Read the data.")):
        edition = Edition(code)
        script = {"duration": DURATION, "segments": [{"id": "01", "text": text}]}
        put(root / edition.script, script)
        segment = {"id": "01", "text": text, "words": []}
        put(edition.timeline, {**script, "segments": [segment], "captions": []})
        put(edition.soundtrack, f"{code} narration")
        assembly = {
            "script_sha256": repository.sha(edition.script),
            "soundtrack_sha256": repository.sha(edition.soundtrack),
        }
        put(edition.audio_assembly, assembly)
    return root


@pytest.fixture
def staged():
    """The Chinese edition, staged complete at the UHD frame."""
    edition = Edition("zh")
    picture_rendering.stage_picture(edition, None, DURATION, 3840, 2160)
    return edition


def renderer(folder, body):
    """A stand-in renderer: an executable Python script that runs `body`."""
    path = folder / "hyperframes"
    path.write_text(f"#!{sys.executable}\n{textwrap.dedent(body)}")
    path.chmod(0o755)
    return path


def completed_receipt(edition):
    """A receipt of a completed render of the current stage, beside its picture."""
    stage, picture = edition.picture_stage, edition.picture
    put(picture, "rendered picture")
    return {
        "command": ["hyperframes", "render", str(stage), "--output", str(picture)],
        "exit": 0,
        "timed_out": False,
        "source_sha256": repository.sha(stage / "index.html"),
        "output_path": str(picture),
        "output_sha256": repository.sha(picture),
    }


def gone(pid, wait=5.0):
    """Whether a process has exited and been reaped within `wait` seconds."""
    ends = time.monotonic() + wait
    while time.monotonic() < ends:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_receipt_paths_name_their_place_below_any_checkout_root(tmp_path):
    root = tmp_path / "restored"
    picture = root / "build/artifacts/film/zh/ddwg-final-picture.mp4"
    elsewhere = "/elsewhere/checkout/build/artifacts/film"
    assert picture_rendering.recorded_at(f"{elsewhere}/zh/ddwg-final-picture.mp4", picture, root)
    assert picture_rendering.recorded_at(str(picture), picture, root)
    assert not picture_rendering.recorded_at(
        f"{elsewhere}/en/ddwg-final-picture.mp4", picture, root
    )
    assert not picture_rendering.recorded_at("ddwg-final-picture.mp4", picture, root)


@pytest.mark.parametrize("code", ["zh", "en"])
def test_staging_twice_writes_the_same_complete_document(code):
    edition = Edition(code)
    stage = edition.picture_stage
    written = []
    for _ in range(2):
        picture_rendering.stage_picture(edition, None, DURATION, 3840, 2160)
        written.append(((stage / "index.html").read_bytes(), (stage / "stage.json").read_bytes()))
    assert written[0] == written[1]
    document = written[0][0].decode()
    template = (COMPOSITION / "index.html").read_text()
    for placeholder in PLACEHOLDERS:
        assert placeholder in template
        assert placeholder not in document
    assert f'<html lang="{"en" if code == "en" else "zh-CN"}">' in document
    assert f'data-duration="{DURATION}"' in document
    assert '<div style="width:3840px;height:2160px" id="film"' in document
    assert "<script>" + (COMPOSITION / "film.js").read_text() + "</script>" in document
    assert "<style>" + (COMPOSITION / "film.css").read_text() + "</style>" in document
    film = json.loads(document.split("window.FILM=", 1)[1].split(";</script>", 1)[0])
    assert (film["edition"], film["render_offset"]) == (code, 0)
    binding = json.loads(written[0][1])
    inputs, timeline = picture_rendering.candidate_picture_inputs(edition)
    assert binding["inputs"] == inputs
    assert film == {**timeline, "render_offset": 0, "edition": code}
    assert [(member["path"], member["source"]) for member in binding["members"]] == [
        (path, str(source)) for path, source in picture_rendering.STAGED_MEMBERS
    ]
    for member in binding["members"]:
        assert repository.sha(stage / member["path"]) == member["sha256"]


def test_staging_reads_each_bound_input_once(root, monkeypatch):
    # The stage inlines the very timeline whose bytes it binds.
    edition = Edition("zh")
    opened = []
    path_open = Path.open

    def counted(self, *args, **kwargs):
        opened.append(self)
        return path_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    picture_rendering.stage_picture(edition, None, DURATION, 3840, 2160)
    for path in (root / edition.script, edition.timeline, edition.audio_assembly):
        assert opened.count(path) == 1


def test_candidate_inputs_refuse_a_timeline_or_soundtrack_of_other_sources():
    edition = Edition("zh")
    timeline = json.loads(edition.timeline.read_text())
    put(edition.timeline, {**timeline, "duration": DURATION - 1})
    with pytest.raises(PictureError, match="timeline differs from its authored script"):
        picture_rendering.candidate_picture_inputs(edition)
    put(edition.timeline, timeline)
    put(edition.soundtrack, "another narration")
    with pytest.raises(PictureError, match="soundtrack differs from its native assembly"):
        picture_rendering.candidate_picture_inputs(edition)


def test_staging_refuses_other_frames_durations_and_places(root):
    edition = Edition("zh")
    for duration, size, start in ((DURATION + 1, (3840, 2160), 0), (DURATION, (1280, 720), 0)):
        with pytest.raises(PictureError, match="admitted frame and duration"):
            picture_rendering.stage_picture(edition, None, duration, *size, start)
    with pytest.raises(PictureError, match="build owner"):
        picture_rendering.stage_picture(edition, root / "elsewhere", DURATION, 3840, 2160)
    assert not edition.picture_stage.exists()


def test_the_document_refuses_a_template_pattern_it_does_not_find_exactly(root):
    edition = Edition("zh")
    template = root / picture_rendering.COMPOSITION / "index.html"
    text = template.read_text()
    for changed, pattern in (
        (text.replace('data-width="1920"', 'data-width="1600"'), 'data-width="1920"'),
        (text.replace("</body>", '<div id="film"></div></body>'), '<div id="film"'),
        (text.replace('data-duration="1200" data-fps', "data-fps"), 'data-duration="1200"'),
    ):
        template.write_text(changed)
        with pytest.raises(PictureError, match=re.escape(repr(pattern))):
            picture_rendering.picture_html(edition, DURATION, 3840, 2160, 0)


def test_a_completed_render_binds_only_the_current_stage(staged):
    edition = staged
    receipt = completed_receipt(edition)
    picture_rendering.validate_picture_binding(edition, receipt)
    # A failed, timed-out or misplaced render is refused by a named error, not an assert.
    for change in (
        {"exit": 1},
        {"timed_out": True},
        {"output_sha256": "0" * 64},
        {"output_path": "/elsewhere/build/artifacts/film/en/ddwg-final-picture.mp4"},
        {"command": ["hyperframes", "render", "/elsewhere/stage", "--output"]},
    ):
        with pytest.raises(PictureError):
            picture_rendering.validate_picture_binding(edition, {**receipt, **change})
    # A document edited after staging no longer derives from the current sources, even
    # when its render receipt names it.
    document = edition.picture_stage / "index.html"
    original = document.read_text()
    document.write_text(original.replace("<title>", "<title>Edited "))
    edited = {**receipt, "source_sha256": repository.sha(document)}
    with pytest.raises(PictureError, match="staged document differs"):
        picture_rendering.validate_picture_binding(edition, edited)
    document.write_text(original)
    picture_rendering.validate_picture_binding(edition, receipt)


def test_a_changed_template_or_copied_member_refuses_the_stage(staged, root):
    edition = staged
    receipt = completed_receipt(edition)
    template = root / picture_rendering.COMPOSITION / "index.html"
    original = template.read_text()
    template.write_text(original.replace("<title>", "<title>Changed "))
    with pytest.raises(PictureError, match="template_sha256"):
        picture_rendering.validate_picture_binding(edition, receipt)
    template.write_text(original)
    font = edition.picture_stage / "fonts/IBMPlexSans-Bold.ttf"
    font.write_text("another font")
    with pytest.raises(PictureError, match=re.escape("fonts/IBMPlexSans-Bold.ttf")):
        picture_rendering.validate_picture_binding(edition, receipt)
    # A record that drops its members cannot pass by checking none of them.
    record = edition.picture_stage / "stage.json"
    put(record, {**json.loads(record.read_text()), "members": []})
    with pytest.raises(PictureError, match="declared members"):
        picture_rendering.require_current_stage(edition, edition.picture_stage)


def test_rendering_records_a_completed_render_that_binds(staged, root, tmp_path):
    edition = staged
    fake = renderer(
        tmp_path,
        """
        import json, os, sys
        output = sys.argv[sys.argv.index("--output") + 1]
        with open(output, "w") as picture:
            picture.write("rendered picture")
        observed = {
            "stdin": sys.stdin.read(),
            "session_leader": os.getsid(0) == os.getpid(),
            "cwd": os.getcwd(),
        }
        with open(sys.argv[0] + ".json", "w") as record:
            json.dump(observed, record)
        """,
    )
    picture_rendering.render_picture(edition, fake, 60)
    receipt = repository.read(edition.render_receipt)
    assert list(receipt) == RECEIPT_KEYS
    stage, picture = edition.picture_stage, edition.picture
    assert receipt["command"][:5] == [str(fake), "render", str(stage), "--output", str(picture)]
    assert receipt["command"][5:7] == ["--fps", str(FPS)]
    assert (receipt["exit"], receipt["timed_out"], receipt["deadline_seconds"]) == (0, False, 60)
    assert receipt["source_sha256"] == repository.sha(stage / "index.html")
    assert receipt["output_sha256"] == repository.sha(picture)
    observed = json.loads(Path(f"{fake}.json").read_text())
    assert observed == {"stdin": "", "session_leader": True, "cwd": str(root)}
    picture_rendering.validate_picture_binding(edition, receipt)


def test_rendering_refuses_a_failed_render_after_recording_it(staged, tmp_path):
    edition = staged
    with pytest.raises(PictureError, match="did not complete"):
        picture_rendering.render_picture(edition, renderer(tmp_path, "raise SystemExit(3)"), 60)
    receipt = repository.read(edition.render_receipt)
    assert (receipt["exit"], receipt["timed_out"], receipt["output_sha256"]) == (3, False, None)


def test_failed_rendering_stops_its_remaining_workers(staged, tmp_path, monkeypatch):
    monkeypatch.setattr(picture_rendering, "STOP_GRACE_SECONDS", 0.5)
    worker = tmp_path / "worker.py"
    worker.write_text(
        textwrap.dedent(
            """
            import os, pathlib, signal, sys, time
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            pathlib.Path(sys.argv[0]).with_suffix(".pid").write_text(str(os.getpid()))
            time.sleep(60)
            """
        )
    )
    fake = renderer(
        tmp_path,
        f"""
        import pathlib, subprocess, sys, time
        subprocess.Popen([sys.executable, {str(worker)!r}])
        while not pathlib.Path({str(worker.with_suffix(".pid"))!r}).exists():
            time.sleep(0.01)
        raise SystemExit(3)
        """,
    )
    try:
        with pytest.raises(PictureError, match="did not complete"):
            picture_rendering.render_picture(staged, fake, 10)
        receipt = repository.read(staged.render_receipt)
        assert (receipt["exit"], receipt["timed_out"]) == (3, False)
        assert gone(int(worker.with_suffix(".pid").read_text()))
    finally:
        if worker.with_suffix(".pid").exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(worker.with_suffix(".pid").read_text()), signal.SIGKILL)


def test_rendering_refuses_a_stale_stage_before_running(staged, root, tmp_path):
    edition = staged
    template = root / picture_rendering.COMPOSITION / "index.html"
    template.write_text(template.read_text().replace("<title>", "<title>Changed "))
    fake = renderer(tmp_path, "open(__file__ + '.ran', 'w').close()")
    with pytest.raises(PictureError, match="template_sha256"):
        picture_rendering.render_picture(edition, fake, 60)
    assert not Path(f"{fake}.ran").exists()
    assert not edition.render_receipt.exists()


def test_rendering_stops_the_whole_process_group_at_its_deadline(staged, tmp_path, monkeypatch):
    # The renderer ignores SIGTERM and its worker obeys it: the group is sent SIGTERM at
    # the deadline and SIGKILL after the grace, and neither process outlives the render.
    monkeypatch.setattr(picture_rendering, "STOP_GRACE_SECONDS", 0.5)
    edition = staged
    worker = tmp_path / "worker.py"
    worker.write_text(
        textwrap.dedent(
            """
            import os, pathlib, signal, sys, time
            here = pathlib.Path(sys.argv[0]).parent
            def stop(*_):
                (here / "worker-terminated").write_text("")
                sys.exit(0)
            signal.signal(signal.SIGTERM, stop)
            (here / "worker.pid").write_text(str(os.getpid()))
            time.sleep(60)
            """
        )
    )
    fake = renderer(
        tmp_path,
        f"""
        import os, pathlib, signal, subprocess, sys, time
        here = pathlib.Path(sys.argv[0]).parent
        subprocess.Popen([sys.executable, {str(worker)!r}])
        while not (here / "worker.pid").exists():
            time.sleep(0.01)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        (here / "renderer.pid").write_text(str(os.getpid()))
        time.sleep(60)
        """,
    )
    started = time.monotonic()
    with pytest.raises(PictureError, match="did not complete"):
        picture_rendering.render_picture(edition, fake, 2)
    assert time.monotonic() - started < 10
    receipt = repository.read(edition.render_receipt)
    assert (receipt["exit"], receipt["timed_out"]) == (None, True)
    assert receipt["elapsed_seconds"] >= 2
    assert (tmp_path / "worker-terminated").exists()
    assert gone(int((tmp_path / "renderer.pid").read_text()))
    assert gone(int((tmp_path / "worker.pid").read_text()))


def test_the_rendered_picture_meets_the_shared_video_contract(staged, monkeypatch):
    edition = staged
    repository.write(edition.render_receipt, completed_receipt(edition))
    cover = {"codec_type": "video", "disposition": {"attached_pic": 1}, "width": 640}
    video = {
        "codec_type": "video",
        "disposition": {"attached_pic": 0},
        "nb_frames": str(DURATION * FPS),
        "avg_frame_rate": "60/1",
        "width": 3840,
        "height": 2160,
        "duration": f"{DURATION + 1e-7}",
    }
    probed = {"streams": [cover, video], "format": {"duration": f"{DURATION:.6f}"}}
    cadence = []
    monkeypatch.setattr(media, "probe", lambda _: probed)
    monkeypatch.setattr(media, "video_cadence", lambda *arguments: cadence.append(arguments))
    # The video stream is found by type behind a cover, and durations agree within 1e-6 s.
    assert picture_rendering.validate_picture(edition)["exit"] == 0
    assert cadence == [(edition.picture, DURATION * FPS, FPS)]
    for change in ({"nb_frames": str(DURATION * FPS - 1)}, {"avg_frame_rate": "30/1"}):
        probed["streams"] = [cover, {**video, **change}]
        with pytest.raises(media.MediaError, match="Video differs"):
            picture_rendering.validate_picture(edition)
