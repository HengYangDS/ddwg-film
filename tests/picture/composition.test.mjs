/** Exercise this film's composition, picture/film.js, on the installed engine's headless runtime: every authored scene
 * against both scripts, speech over a picture, each paint traced to its scene, the camera, the label breaks and the
 * pinned timeline engine. The engine's own tools are tested in filmkit. */
import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { engineModule } from "../engine.mjs";

const { canvasStandIn, openComposition } = await import(
  engineModule("picture/headless-composition.mjs")
);

// Scripts run in a context keep their file name, so coverage attributes them to their sources.
const ENGINE = fileURLToPath(new URL("../../node_modules/gsap/dist/gsap.min.js", import.meta.url));
const COMPOSITION = fileURLToPath(new URL("../../picture/film.js", import.meta.url));

async function authoredTimeline(code) {
  const script = JSON.parse(
    await readFile(
      new URL(
        code === "zh" ? "../../content/film-script.json" : "../../content/en/film-script.json",
        import.meta.url,
      ),
      "utf8",
    ),
  );
  let cursor = 3;
  const segments = script.segments.map((segment, index) => {
    if (index) cursor += script.segments[index - 1].chapter === segment.chapter ? 1.8 : 3.6;
    const tokens =
      code === "zh"
        ? segment.text.match(/[\p{Script=Han}]|[A-Za-z0-9][A-Za-z0-9'’.-]*/gu)
        : segment.text.split(/\s+/).filter(Boolean);
    const voiceStart = cursor;
    const words = tokens.map((text) => {
      const word = { text, start: cursor, end: cursor + 0.18 };
      cursor += 0.2;
      return word;
    });
    return { ...segment, voice_start: voiceStart, voice_end: cursor, words };
  });
  segments.forEach((segment, index) => {
    segment.start = index
      ? segment.voice_start - 0.6 * (segment.voice_start - segments[index - 1].voice_end)
      : 0;
  });
  const duration = cursor + 6;
  segments.forEach((segment, index) => {
    segment.end = segments[index + 1]?.start ?? duration - script.credits_duration;
  });
  return { ...script, segments, captions: [], duration, edition: code, render_offset: 0 };
}

for (const code of ["zh", "en"]) {
  test(`${code} composition paints every authored scene from its own spoken cues`, async () => {
    const film = await authoredTimeline(code);
    const composition = openComposition(film);
    const painted = new Set();
    for (const segment of film.segments) {
      for (const q of [0.15, 0.5, 0.85, 1]) {
        const { texts } = composition.render(
          segment.voice_start + q * (segment.voice_end - segment.voice_start),
        );
        for (const v of texts) if (v.scene) painted.add(v.scene);
        assert.ok(
          texts.every((v) => v.bounds.every(Number.isFinite)),
          segment.id,
        );
      }
    }
    assert.equal(painted.size, film.segments.length);
    assert.ok(composition.render(film.duration - 1).texts.some((v) => v.text === "Yang HENG"));
  });
}

for (const code of ["zh", "en"]) {
  test(`${code} speech never plays over an empty picture`, async () => {
    const film = await authoredTimeline(code);
    // A firm stroke or fill counts for the scene that paints it, as the film publishes while it draws, so the film's
    // own cuts and camera apply: no scene function is replaced.
    let marks = 0;
    const composition = openComposition(film),
      count = (paint) => {
        if (paint.scene && paint.kind !== "text" && paint.alpha > 0.35) marks++;
      };
    const runs = [];
    for (const segment of film.segments) {
      let run = null;
      for (let t = segment.voice_start; t < segment.voice_end; t += 0.1) {
        marks = 0;
        const { texts } = composition.render(t, count);
        const empty = !marks && !texts.some((v) => v.scene && v.alpha > 0.35);
        if (empty) run ??= { segment: segment.id, start: t, end: t };
        if (empty) run.end = t + 0.1;
        if (!empty && run) {
          runs.push(run);
          run = null;
        }
      }
      if (run) runs.push(run);
    }
    assert.deepEqual(
      runs
        .filter((run) => run.end - run.start > 0.5)
        .map((run) => `${run.segment}@${run.start.toFixed(1)}`),
      [],
    );
  });
}

test("every paint of a scene is traced to its line of film.js, however deep its helpers", async () => {
  const film = await authoredTimeline("en"),
    origins = [];
  const composition = openComposition(film);
  // Scene 04 grows its names through helpers nested more deeply than V8's default ten frames.
  const scene = film.segments.find((v) => v.id === "04");
  for (const q of [0.5, 0.9])
    composition.render(scene.voice_start + q * (scene.voice_end - scene.voice_start), (paint) =>
      origins.push([paint.scene, composition.origin()]),
    );
  const lines = (await readFile(COMPOSITION, "utf8")).split("\n");
  const traced = origins.filter(([scene]) => scene).map(([, origin]) => origin);
  assert.ok(traced.length > 0 && traced.every(Boolean));
  for (const origin of traced.filter(Boolean)) {
    const line = Number(/^film\.js:(\d+)$/.exec(origin)[1]),
      above = lines.slice(0, line);
    const opened = above.findLastIndex((v) => /^scenes\["\d+"\] = function/.test(v));
    assert.ok(opened >= 0 && opened > above.slice(0, -1).lastIndexOf("};"), origin);
  }
  // The caption and the running head are painted outside every scene.
  assert.ok(origins.filter(([scene]) => !scene).every(([, origin]) => origin === null));
});

test("the film's own camera frames each scene", async () => {
  const film = await authoredTimeline("zh"),
    composition = openComposition(film);
  for (const segment of film.segments) {
    const camera = composition.camera(segment, (segment.start + segment.end) / 2);
    assert.ok(camera.k >= 1 && camera.k < 1.1, segment.id);
    assert.ok([camera.ox, camera.oy, camera.ax, camera.ay].every(Number.isFinite), segment.id);
  }
  assert.match(composition.palette.ground, /^#[0-9A-F]{6}$/i);
});

test("the vendored timeline engine seeks a paused timeline as the composition drives it", async () => {
  const scope = { console, setTimeout, clearTimeout };
  vm.createContext(scope);
  vm.runInContext(await readFile(ENGINE, "utf8"), scope, { filename: ENGINE });
  const { gsap } = scope.window;
  assert.equal(gsap.version, "3.15.0");
  const playhead = { time: 0 };
  const timeline = gsap.timeline({ paused: true });
  timeline.to(playhead, { time: 1500, duration: 1500, ease: "none" }, 0);
  timeline.seek(50);
  assert.equal(playhead.time, 50);
  timeline.kill();
  gsap.ticker.sleep();
});

async function wrapInComposition(film) {
  const window = { FILM: film },
    ctx = canvasStandIn(() => {}),
    elements = { picture: { getContext: () => ctx }, film: { dataset: { width: "1920" } } };
  const context = vm.createContext({
    window,
    document: { getElementById: (id) => elements[id] },
  });
  vm.runInContext(await readFile(COMPOSITION, "utf8"), context, { filename: COMPOSITION });
  return (v, width, size) =>
    vm.runInContext(`wrapName(${JSON.stringify(v)}, ${width}, ${size})`, context);
}

test("a Chinese name breaks only after a list or clause mark, and keeps every character", async () => {
  const wrapName = await wrapInComposition(await authoredTimeline("zh"));
  const joint = /[、，。；：,]$/u;
  for (const [v, width] of [
    ["生产环境、共享资产，或者风控、监管报送这类关键管理链条", 480],
    ["上报、交给人接管", 230],
  ]) {
    const lines = wrapName(v, width, 26);
    assert.equal(lines.join(""), v, lines.join("|"));
    assert.ok(lines.length > 1, v);
    for (const line of lines.slice(0, -1)) assert.match(line, joint, `${v} broke after ${line}`);
  }
  // Where its lines fit, a clause mark ends a line before a list mark does, so an alternative keeps its examples
  // together; where they do not, a list mark ends it.
  const vault = "生产环境、共享资产，或者风控、监管报送这类关键管理链条";
  // The lines come from the composition's own realm, so they are copied before they are compared.
  assert.deepEqual(
    [...wrapName(vault, 560, 26)],
    ["生产环境、共享资产，", "或者风控、监管报送这类关键管理链条"],
  );
  assert.deepEqual(
    [...wrapName(vault, 480, 26)],
    ["生产环境、共享资产，或者风控、", "监管报送这类关键管理链条"],
  );
  // A name with no mark breaks between characters, so a label whose break would split a word is authored as its lines.
  const plain = wrapName("证据要对得上当前的版本", 230, 26);
  assert.equal(plain.join(""), "证据要对得上当前的版本");
  assert.ok(
    plain.every((line) => line.length <= 9),
    plain.join("|"),
  );
});

test("a label whose words hold no joint is authored as its lines", async () => {
  const film = await authoredTimeline("zh"),
    texts = new Set(),
    composition = openComposition(film);
  // Each label is named late in its stage, so the whole segment is read rather than a sample of it.
  for (const segment of film.segments.filter((v) => ["09", "14", "21"].includes(v.id)))
    for (let t = segment.voice_start; t < segment.voice_end; t += 0.5)
      for (const v of composition.render(t).texts) texts.add(v.text);
  for (const line of [
    "证据要对得上",
    "当前的版本",
    "看起来有效的",
    "模型信号",
    "跑完和说法对得上的",
    "核验",
  ])
    assert.ok(texts.has(line), `missing line ${line}`);
  for (const v of texts) assert.ok(!/^的/u.test(v), `a line begins with 的: ${v}`);
});
