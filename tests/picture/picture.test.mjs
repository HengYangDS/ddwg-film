/** Exercise the picture tools: the frame rules of the real-browser check, with its page program and instrumentation on
 * the headless canvas; the headless runtime both audits run the composition on; every authored scene against both
 * scripts; the audits' invocations; the seat check; and the timeline engine. */
import test, { after } from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  analysis,
  bandCover,
  faintLabels,
  fillShare,
  inkLevel,
  inspectFilm,
  instrument,
  listTracker,
  litLevel,
  nameRules,
  pictureOffset,
  readingLoad,
  strokeShare,
} from "../../src/ddwg_film/picture/geometry-check.mjs";
import {
  canvasStandIn,
  canvasSweep,
  openComposition,
  readTimeline,
} from "../../src/ddwg_film/picture/headless-composition.mjs";
import { containerFill, seatMarks } from "../../src/ddwg_film/picture/seat-marks.mjs";

// Each folder a test writes its inputs and outputs into is removed once the file's tests have run.
const folders = [];
after(() => Promise.all(folders.map((folder) => rm(folder, { recursive: true, force: true }))));
async function scratchFolder() {
  const folder = await mkdtemp(join(tmpdir(), "ddwg-picture-"));
  folders.push(folder);
  return folder;
}

// Scripts run in a context keep their file name, so coverage attributes them to their sources.
const ENGINE = fileURLToPath(new URL("../../assets/vendor/gsap/gsap.min.js", import.meta.url));

// The rules are measured against the film's own palette, as the composition defines it.
const { palette } = openComposition(await authoredTimeline("zh"));
const inspectFrame = analysis(inkLevel(palette));
const contrast = readingLoad(palette);
const label = (text, bounds, extra = {}) => ({
  text,
  bounds,
  alpha: 1,
  role: "label",
  scene: "01",
  seq: 10,
  ...extra,
});
const stroke = (points, extra = {}) => ({
  kind: "stroke",
  seq: 1,
  alpha: 1,
  width: 2,
  subs: [points],
  ...extra,
});
const fill = (box, extra = {}) => ({ kind: "fill", seq: 1, alpha: 1, box, ...extra });
const kinds = (findings) => findings.map((finding) => finding.kind).sort();
const names = nameRules();
const word = (text, extra = {}) => ({
  text,
  bounds: [0, 0, 10, 10],
  alpha: 1,
  role: "label",
  scene: "09",
  color: "#ECE8DF",
  whole: text,
  placed: true,
  size: 26,
  set: null,
  ...extra,
});

test("visible labels must stay apart and inside the safe area", () => {
  assert.deepEqual(
    kinds(inspectFrame([label("A", [300, 300, 400, 330]), label("B", [390, 310, 480, 340])], [])),
    ["label_overlap"],
  );
  assert.deepEqual(
    kinds(inspectFrame([label("A", [300, 300, 400, 330]), label("B", [402, 300, 480, 330])], [])),
    [],
  );
  assert.deepEqual(kinds(inspectFrame([label("A", [30, 300, 120, 330])], [])), [
    "outside_safe_area",
  ]);
  assert.deepEqual(
    kinds(inspectFrame([label("Caption", [30, 990, 1890, 1012], { role: "caption" })], [])),
    [],
  );
  assert.deepEqual(kinds(inspectFrame([label("A", [70, 300, 160, 330])], [])), [
    "outside_safe_area",
  ]);
  assert.deepEqual(kinds(inspectFrame([label("A", [30, 300, 120, 330], { alpha: 0.3 })], [])), [
    "outside_safe_area",
  ]);
  assert.deepEqual(kinds(inspectFrame([label("A", [30, 300, 120, 330], { alpha: 0.1 })], [])), []);
  // Labels end clear of the caption band.
  assert.deepEqual(kinds(inspectFrame([label("A", [300, 900, 400, 936])], [])), [
    "outside_safe_area",
  ]);
  assert.deepEqual(kinds(inspectFrame([label("A", [300, 880, 400, 916])], [])), []);
});

test("reading contrast separates legible names from faint clutter and gone residue", () => {
  // Every palette colour, the warning colour included, reads at 3:1 at .68 of its ink and is gone below 1.8:1 at .18.
  assert.ok(contrast("#ECE8DF", 1) > 14);
  for (const color of ["#ECE8DF", "#9BA8B1", "#7DB7D8", "#E0BF78", "#C9785C"]) {
    assert.ok(contrast(color, 0.68) >= 3, color);
    assert.ok(contrast(color, 0.18) < 1.8, color);
  }
  assert.ok(contrast("#ECE8DF", 0.4) >= 1.8 && contrast("#ECE8DF", 0.4) < 3.4);
});

test("names are read whole and at most twelve are legible at once", () => {
  const many = Array.from({ length: 13 }, (_, i) => word(`名${i}`));
  assert.deepEqual(kinds(names(many, contrast)), ["name_load"]);
  assert.deepEqual(kinds(names(many.slice(0, 12), contrast)), []);
  // The lines of a wrapped name share one whole and count once; a name below 3:1 is not read.
  const wrapped = [
    ...many.slice(0, 11),
    word("第一行", { whole: "第一行 第二行" }),
    word("第二行", { whole: "第一行 第二行" }),
  ];
  assert.deepEqual(kinds(names(wrapped, contrast)), []);
  assert.deepEqual(kinds(names([...many.slice(0, 12), word("淡", { alpha: 0.2 })], contrast)), []);
});

test("every legible name is placed by a layout primitive", () => {
  assert.deepEqual(kinds(names([word("手放", { placed: false })], contrast)), ["unplaced_label"]);
  assert.deepEqual(kinds(names([word("手放", { placed: false, alpha: 0.2 })], contrast)), []);
});

test("names use at most two text sizes and never join items with a dot", () => {
  assert.deepEqual(
    kinds(names([word("甲"), word("乙", { size: 22 }), word("丙", { size: 28 })], contrast)),
    ["type_sizes"],
  );
  assert.deepEqual(kinds(names([word("甲"), word("乙", { size: 22 })], contrast)), []);
  assert.deepEqual(kinds(names([word("来源 · 时间")], contrast)), ["dot_join"]);
});

test("a list leaves whole, every name at its set's level", () => {
  const dimmed = listTracker();
  dimmed.see([word("甲", { set: "a", alpha: 0.58 }), word("乙", { set: "a" })], 10, contrast);
  assert.deepEqual(kinds(dimmed.findings()), ["list_leaving_dimmed"]);
  const whole = listTracker();
  whole.see([word("甲", { set: "a", alpha: 0.58 }), word("乙", { set: "a" })], 10, contrast);
  whole.see([word("甲", { set: "a" }), word("乙", { set: "a" })], 10.2, contrast);
  assert.deepEqual(kinds(whole.findings()), []);
  // A refused name is muted by design, so it is held to its own colour, not to the set's ink.
  const refused = listTracker();
  refused.see(
    [word("甲", { set: "a" }), word("拒", { set: "a", color: "#9BA8B1", alpha: 0.7 })],
    10,
    contrast,
  );
  assert.deepEqual(kinds(refused.findings()), []);
});

test("a list leaves as a whole", () => {
  const early = listTracker();
  early.see([word("甲", { set: "a" }), word("乙", { set: "a" })], 10, contrast);
  early.see([word("乙", { set: "a" })], 11, contrast);
  assert.deepEqual(kinds(early.findings()), ["list_leaving_early"]);
  const whole = listTracker();
  whole.see([word("甲", { set: "a" }), word("乙", { set: "a" })], 10, contrast);
  whole.see([word("乙", { set: "a" })], 10.5, contrast);
  assert.deepEqual(kinds(whole.findings()), []);
});

test("the second list level stays legible in every name colour", () => {
  // Ink, muted, evidence and authority at the second level (0.58); the unknown colour never names.
  for (const color of ["#ECE8DF", "#9BA8B1", "#7DB7D8", "#E0BF78"])
    assert.ok(contrast(color, 0.58) >= 3, color);
});

test("shapes stay inside the action-safe area", () => {
  assert.deepEqual(
    kinds(
      inspectFrame(
        [],
        [
          stroke([
            [1400, 600],
            [1880, 600],
          ]),
        ],
      ),
    ),
    ["stroke_outside_action_safe"],
  );
  assert.deepEqual(kinds(inspectFrame([], [fill([1360, 580, 1880, 620])])), [
    "fill_outside_action_safe",
  ]);
  assert.deepEqual(
    kinds(
      inspectFrame(
        [],
        [
          stroke([
            [100, 60],
            [1820, 1020],
          ]),
        ],
      ),
    ),
    [],
  );
  assert.deepEqual(
    kinds(
      inspectFrame(
        [],
        [
          stroke(
            [
              [1400, 600],
              [1880, 600],
            ],
            { alpha: 0.1 },
          ),
        ],
      ),
    ),
    [],
  );
});

test("strokes may not cross a label unless an opaque card painted after them hides them", () => {
  const word = label("Word", [300, 300, 400, 330]);
  const crossing = stroke([
    [250, 315],
    [450, 315],
  ]);
  assert.deepEqual(kinds(inspectFrame([word], [crossing])), ["label_stroke_collision"]);
  assert.deepEqual(
    kinds(
      inspectFrame(
        [word],
        [
          stroke([
            [250, 360],
            [450, 360],
          ]),
        ],
      ),
    ),
    [],
  );
  const card = fill([280, 290, 420, 340], { seq: 5 });
  assert.deepEqual(kinds(inspectFrame([word], [crossing, card])), []);
  assert.deepEqual(kinds(inspectFrame([word], [{ ...card, alpha: 0.5 }, crossing])), [
    "label_stroke_collision",
  ]);
});

test("a fill may contain a label but may not cut through it", () => {
  const word = label("Word", [300, 300, 400, 330]);
  assert.deepEqual(kinds(inspectFrame([word], [fill([280, 290, 420, 340])])), []);
  assert.deepEqual(kinds(inspectFrame([word], [fill([350, 290, 500, 340])])), [
    "label_fill_collision",
  ]);
  assert.deepEqual(
    kinds(
      inspectFrame(
        [label("Caption", [300, 300, 400, 330], { role: "caption" })],
        [fill([350, 290, 500, 340])],
      ),
    ),
    [],
  );
});

test("a frame that must paint may not dim to bare ground", () => {
  const caption = label("Caption", [300, 990, 400, 1012], {
    role: "caption",
    scene: null,
    color: "#ECE8DF",
  });
  const mark = (color, alpha, scene = "05") =>
    stroke(
      [
        [300, 300],
        [400, 300],
      ],
      { scene, alpha, color },
    );
  assert.deepEqual(kinds(inspectFrame([caption], [], { mustPaint: true, scene: "05" })), [
    "bare_ground",
  ]);
  // The brightest scene mark must rise 30 levels above the ground: ink at 20% does, ink at 10% or a dim line does not.
  assert.deepEqual(kinds(inspectFrame([caption], [mark("#ECE8DF", 0.2)], { mustPaint: true })), []);
  assert.deepEqual(kinds(inspectFrame([caption], [mark("#ECE8DF", 0.1)], { mustPaint: true })), [
    "bare_ground",
  ]);
  assert.deepEqual(kinds(inspectFrame([caption], [mark("#34424E", 0.5)], { mustPaint: true })), [
    "bare_ground",
  ]);
  assert.deepEqual(kinds(inspectFrame([], [mark("#ECE8DF", 1, null)], { mustPaint: true })), [
    "bare_ground",
  ]);
  assert.deepEqual(
    kinds(
      inspectFrame([label("Word", [300, 300, 400, 330], { alpha: 0.03, color: "#ECE8DF" })], [], {
        mustPaint: true,
      }),
    ),
    ["bare_ground"],
  );
  assert.deepEqual(kinds(inspectFrame([caption], [])), []);
  // The head band frames the picture: the Illustrative chip alone leaves the frame bare.
  const chip = label("Illustrative", [1640, 60, 1800, 90], { scene: "05", color: "#ECE8DF" });
  assert.deepEqual(
    kinds(
      inspectFrame(
        [chip],
        [
          stroke(
            [
              [1630, 56],
              [1810, 56],
            ],
            { scene: "05", color: "#ECE8DF" },
          ),
        ],
        { mustPaint: true },
      ),
    ),
    ["bare_ground"],
  );
  assert.deepEqual(kinds(inspectFrame([chip], [mark("#ECE8DF", 0.5)], { mustPaint: true })), []);
  // The frame reports its brightest scene level, so a run of faint speech can be found across frames.
  assert.equal(
    inspectFrame([caption], [mark("#ECE8DF", 0.5)], { mustPaint: true }).brightest,
    110.5,
  );
  assert.equal(inspectFrame([caption], [], { mustPaint: true }).brightest, 0);
});

test("a chapter's first word lands on a standing first scene", () => {
  const mark = (alpha) =>
    stroke(
      [
        [300, 300],
        [400, 300],
      ],
      { scene: "09", alpha, color: "#ECE8DF" },
    );
  assert.deepEqual(kinds(inspectFrame([], [mark(0.3)], { mustPaint: true, firstWord: true })), [
    "faint_first_word",
  ]);
  assert.deepEqual(kinds(inspectFrame([], [mark(0.5)], { mustPaint: true, firstWord: true })), []);
  assert.deepEqual(kinds(inspectFrame([], [mark(0.3)], { mustPaint: true })), []);
});

test("ink level and reading contrast are measured over the film's ground", () => {
  const level = inkLevel(palette);
  assert.equal(level(palette.ground, 1), 0);
  assert.equal(level("#ECE8DF", 0.5), 110.5);
  // A style without channels, such as a gradient, lifts nothing, and reads as the film's ink.
  assert.equal(level(undefined, 1), 0);
  assert.equal(contrast(undefined, 0.6), contrast(palette.ink, 0.6));
  assert.equal(contrast(palette.ground, 1), 1);
});

test("a fill above 15% opacity that cuts through a label collides, however faint", () => {
  // The frame audit once skipped fills at or below 35% here; both checks now apply this one rule.
  const word = label("Word", [300, 300, 400, 330]);
  for (const alpha of [0.3, 1])
    assert.deepEqual(kinds(inspectFrame([word], [fill([350, 290, 500, 340], { alpha })])), [
      "label_fill_collision",
    ]);
  assert.deepEqual(kinds(inspectFrame([word], [fill([350, 290, 500, 340], { alpha: 0.15 })])), []);
});

test("each finding carries the evidence a report shows", () => {
  const boxed = label("Word", [300, 300, 400, 330]);
  const [crossed] = inspectFrame(
    [boxed],
    [
      stroke([
        [250, 200],
        [250, 315],
        [450, 315],
      ]),
    ],
  );
  assert.deepEqual(crossed, {
    kind: "label_stroke_collision",
    scene: "01",
    text: "Word",
    shape: "stroke",
    bounds: [300, 300, 400, 330],
    graphic: [250, 315, 450, 315],
  });
  assert.deepEqual(
    inspectFrame([boxed, label("Next", [390, 310, 480, 340])], []).map((v) => v.pair),
    [["Word", "Next"]],
  );
  assert.deepEqual(
    inspectFrame([label("A", [30, 300, 120, 330])], [])[0].bounds,
    [30, 300, 120, 330],
  );
  const [outside] = inspectFrame([], [fill([1360, 580, 1880, 620])]);
  assert.deepEqual([outside.shape, outside.point], ["fill", [1880, 620]]);
  // Name findings count the legible names and give the sizes shown.
  const found = names([word("甲"), word("乙", { size: 22 }), word("丙", { size: 28 })], contrast);
  assert.equal(found.names, 3);
  assert.deepEqual(found.find((v) => v.kind === "type_sizes").sizes, [22, 26, 28]);
  // List findings name the set and the name, when it was last seen and a dimmed name's share of the brightest.
  const lists = listTracker();
  lists.see([word("甲", { set: "a" }), word("乙", { set: "a" })], 10, contrast);
  lists.see([word("甲", { set: "a" }), word("乙", { set: "a", alpha: 0.6 })], 11, contrast);
  lists.see([word("乙", { set: "a" })], 12, contrast);
  assert.deepEqual(
    lists.findings().map(({ kind, set, name, at, share }) => [kind, set, name, at, share]),
    [["list_leaving_early", "a", "甲", 11, undefined]],
  );
});

test("a label held faint for more than a second is reported when it leaves the faint band", () => {
  const see = faintLabels(),
    faint = word("淡", { alpha: 0.3 });
  assert.ok(contrast(faint.color, faint.alpha) >= 1.8 && contrast(faint.color, faint.alpha) < 3);
  assert.deepEqual(see([faint], 10, contrast), []);
  assert.deepEqual(see([faint], 11, contrast), []);
  assert.deepEqual(see([], 11.2, contrast), [{ scene: "09", text: "淡", start: 10, end: 11.2 }]);
  // A faint stretch of one second or less is a fade, not clutter.
  assert.deepEqual(see([faint], 20, contrast), []);
  assert.deepEqual(see([word("淡")], 21, contrast), []);
});

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

const COMPOSITION = fileURLToPath(
  new URL("../../src/ddwg_film/picture/composition/film.js", import.meta.url),
);
const spanOf = (points) => [
  Math.min(...points.map((p) => p[0])),
  Math.min(...points.map((p) => p[1])),
  Math.max(...points.map((p) => p[0])),
  Math.max(...points.map((p) => p[1])),
];

test("the headless timeline is the staged one: its language's edition and no render offset unless given", async () => {
  const folder = await scratchFolder(),
    path = join(folder, "timeline.json");
  await writeFile(path, JSON.stringify({ language: "English", duration: 10 }));
  assert.deepEqual(readTimeline(path), {
    language: "English",
    duration: 10,
    edition: "en",
    render_offset: 0,
  });
  await writeFile(
    path,
    JSON.stringify({ language: "Chinese", edition: "zh", render_offset: 12.5 }),
  );
  assert.deepEqual(readTimeline(path), { language: "Chinese", edition: "zh", render_offset: 12.5 });
});

test("each rendered frame hands over every paint with the scene that drew it", async () => {
  const film = await authoredTimeline("zh"),
    paints = [];
  const composition = openComposition(film);
  const segment = film.segments[3],
    { texts } = composition.render(segment.voice_start + 1, (paint) => paints.push(paint));
  assert.ok(paints.some((paint) => paint.scene === segment.id));
  assert.ok(paints.some((paint) => paint.scene === null && paint.kind === "text"));
  // A text paint stands at its anchor, and its box, mapped to the screen, is the box film.js registers for it.
  const words = paints.filter((paint) => paint.kind === "text");
  assert.equal(words.length, texts.length);
  words.forEach((paint, i) => {
    assert.deepEqual([paint.text, paint.scene], [texts[i].text, texts[i].scene]);
    // The layout is built inside the composition's context, so its arrays are copied before comparing.
    assert.deepEqual(spanOf(paint.points.map(paint.toScreen)), [...texts[i].bounds]);
    assert.equal(paint.subs.length, 1);
  });
  // Strokes and fills carry their sampled screen subpaths and their drawing points.
  const shapes = paints.filter((paint) => paint.kind !== "text");
  assert.ok(shapes.length > 0);
  for (const paint of shapes) {
    assert.ok(paint.subs.flat().every((point) => point.every(Number.isFinite)));
    assert.ok(paint.points.length > 0 && paint.scale > 0 && paint.lineWidth > 0);
  }
});

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

test("the canvas stand-in paints what film.js draws and refuses any other member", () => {
  const paints = [],
    ctx = canvasStandIn((paint) => paints.push(paint));
  assert.throws(() => ctx.rotate(1), /The headless canvas has no rotate/);
  assert.throws(() => ctx.toString(), /The headless canvas has no toString/);
  assert.throws(() => {
    ctx.shadowBlur = 4;
  }, /The headless canvas has no shadowBlur to set/);
  // A stroke carries its path as sampled screen subpaths and as its drawing points.
  ctx.setTransform(2, 0, 0, 2, 10, 20);
  ctx.strokeStyle = "#ECE8DF";
  ctx.lineWidth = 3;
  ctx.globalAlpha = 0.5;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(10, 5);
  ctx.closePath();
  ctx.stroke();
  const [line] = paints;
  assert.deepEqual(
    [line.kind, line.color, line.alpha, line.lineWidth, line.scale],
    ["stroke", "#ECE8DF", 0.5, 3, 2],
  );
  assert.deepEqual(line.subs, [
    [
      [10, 20],
      [30, 30],
      [10, 20],
    ],
  ]);
  assert.deepEqual(line.points, [
    [0, 0],
    [10, 5],
  ]);
  assert.deepEqual(line.toScreen([10, 5]), [30, 30]);
  // A restore returns the saved state and transform; one without a saved state does nothing, as on a canvas.
  ctx.save();
  ctx.globalAlpha = 0.2;
  ctx.translate(5, 0);
  ctx.restore();
  ctx.restore();
  assert.equal(ctx.globalAlpha, 0.5);
  assert.deepEqual(ctx.getTransform(), { a: 2, b: 0, c: 0, d: 2, e: 10, f: 20 });
  // An ellipse is sampled as an arc is, every 7.5 degrees, and its whole box spans its drawing points.
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.beginPath();
  ctx.ellipse(100, 100, 40, 20, 0, 0, Math.PI * 2);
  ctx.stroke();
  const [ring] = paints[1].subs;
  assert.equal(ring.length, 49);
  assert.ok(
    ring.every(([x, y]) => Math.abs(((x - 100) / 40) ** 2 + ((y - 100) / 20) ** 2 - 1) < 1e-9),
  );
  assert.deepEqual(spanOf(ring).map(Math.round), [60, 80, 140, 120]);
  assert.deepEqual(paints[1].points, [
    [60, 80],
    [140, 120],
  ]);
  ctx.beginPath();
  ctx.ellipse(0, 0, 40, 20, Math.PI / 2, 0, Math.PI * 2);
  ctx.fill();
  assert.deepEqual(
    paints[2].points.map((point) => point.map(Math.round)),
    [
      [-20, -40],
      [20, 40],
    ],
  );
  // A text stands at its anchor, its box estimated from its font, alignment and baseline: a capital is 0.66 of the
  // size and any other Latin letter 0.54 of it.
  ctx.font = "20px DDWG";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillStyle = "#7DB7D8";
  ctx.fillText("Ab", 50, 60);
  assert.equal(ctx.measureText("Ab").width, 24);
  const word = paints[3];
  assert.deepEqual([word.kind, word.text, word.size, word.color], ["text", "Ab", 20, "#7DB7D8"]);
  assert.deepEqual(word.subs, [[[50, 60]]]);
  assert.deepEqual(
    word.points.map((point) => point.map(Math.round)),
    [
      [38, 60],
      [62, 81],
    ],
  );
  // The ground laid under each frame is never a mark.
  ctx.fillRect(0, 0, 1920, 1080);
  assert.equal(paints.length, 4);
});

/* The real-browser check's page code on the headless canvas: a context class whose methods are the stand-in's, so the
 * check's instrumentation wraps them as it wraps CanvasRenderingContext2D in the browser, and film.js draws on it. */
async function headlessPage(film) {
  const STYLE = [
    "globalAlpha",
    "strokeStyle",
    "fillStyle",
    "lineWidth",
    "lineCap",
    "lineJoin",
  ].concat(["font", "textAlign", "textBaseline", "letterSpacing"]);
  class CanvasRenderingContext2D {
    constructor(inner) {
      this.inner = inner;
    }
  }
  const inner = canvasStandIn(() => {});
  for (const name of Object.keys(inner))
    CanvasRenderingContext2D.prototype[name] = function (...args) {
      return this.inner[name](...args);
    };
  for (const key of STYLE)
    Object.defineProperty(CanvasRenderingContext2D.prototype, key, {
      get() {
        return this.inner[key];
      },
      set(value) {
        this.inner[key] = value;
      },
    });
  const canvas = { getContext: () => new CanvasRenderingContext2D(inner) },
    element = { dataset: { width: "1920" } },
    window = { FILM: film };
  const context = vm.createContext({
    window,
    document: { getElementById: (id) => (id === "picture" ? canvas : element) },
    CanvasRenderingContext2D,
  });
  vm.runInContext(`(${instrument})()`, context);
  vm.runInContext(await readFile(COMPOSITION, "utf8"), context, { filename: COMPOSITION });
  return { window, context };
}

test("the stand-in samples every path as the real-browser instrumentation does", async () => {
  const film = await authoredTimeline("en"),
    { window } = await headlessPage(film),
    paints = [];
  const composition = openComposition(film);
  let ellipses = 0;
  // Scene 16 draws an ellipse, the eye, 77-80% through its speech; the others arcs, curves, rounded boxes and lines.
  for (const segment of film.segments.filter((v) => ["05", "12", "16", "22"].includes(v.id)))
    for (const q of [0.3, 0.6, 0.785, 0.9]) {
      const t = segment.voice_start + q * (segment.voice_end - segment.voice_start);
      paints.length = 0;
      composition.render(t, (paint) => paints.push(paint));
      window.__resetPaint();
      window.renderFrame(t);
      // The page records every stroke, a fill with a path, and the paint order of each text.
      const shapes = paints
        .map((paint, i) => ({ paint, seq: i + 1 }))
        .filter(
          ({ paint }) =>
            paint.kind === "stroke" || (paint.kind === "fill" && paint.subs.flat().length),
        );
      assert.equal(window.__paintedShapes.length, shapes.length, `${segment.id}@${t}`);
      shapes.forEach(({ paint, seq }, k) => {
        // The page's values belong to its own realm; a structured clone compares them by value.
        const shape = structuredClone(window.__paintedShapes[k]);
        assert.deepEqual(
          [shape.kind, shape.seq, shape.alpha, shape.color, shape.scene],
          [paint.kind, seq, paint.alpha, paint.color, paint.scene],
        );
        if (paint.kind === "stroke") {
          assert.equal(shape.width, paint.lineWidth * paint.scale);
          assert.deepEqual(shape.subs, paint.subs);
          ellipses += paint.subs.filter((sub) => {
            const [x0, y0, x1, y1] = spanOf(sub);
            return sub.length === 49 && Math.abs(x1 - x0 - (y1 - y0)) > 1;
          }).length;
        } else assert.deepEqual(shape.box, spanOf(paint.subs.flat()));
      });
      assert.deepEqual(
        [...window.__paintedText],
        paints.flatMap((paint, i) => (paint.kind === "text" ? [i + 1] : [])),
      );
    }
  assert.ok(ellipses > 0);
});

test("the real-browser page program runs every rule from its source and keeps the receipt's fields", async () => {
  const film = await authoredTimeline("zh"),
    { context } = await headlessPage(film);
  const rules = Object.fromEntries(
    [inkLevel, readingLoad, analysis, nameRules, listTracker, faintLabels].map((rule) => [
      rule.name,
      rule.toString(),
    ]),
  );
  // The program runs in the page's realm, as page.evaluate runs it, on the palette read from the page.
  const program = vm.runInContext(`(${inspectFilm})`, context),
    pagePalette = structuredClone(vm.runInContext("({ ...P })", context));
  assert.deepEqual(pagePalette, { ...palette });
  const at = Math.round(film.segments[6].voice_start * 60);
  const result = structuredClone(program(rules, pagePalette, at + 20 * 60, 30, 60));
  assert.equal(result.checked, Math.ceil((at + 20 * 60) / 30));
  assert.deepEqual(result.errors, []);
  assert.ok(result.findings.length > 0);
  for (const finding of result.findings)
    assert.deepEqual(Object.keys(finding), ["kind", "scene", "text", "first", "frames"]);
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

// The headless audits run the composition itself on a timeline; a short stretch exercises every measurement.
const AUDIT_FRAMES = fileURLToPath(
  new URL("../../src/ddwg_film/picture/frame-audit.mjs", import.meta.url),
);
const AUDIT_MOTION = fileURLToPath(
  new URL("../../src/ddwg_film/picture/motion-audit.mjs", import.meta.url),
);

test("the frame audit reports a stretch of the film, its label trace, its marks and its bounds", async () => {
  const film = await authoredTimeline("zh"),
    folder = await scratchFolder();
  const path = join(folder, "timeline.json"),
    trace = join(folder, "trace.tsv"),
    marks = join(folder, "marks.tsv"),
    bounds = join(folder, "bounds.json"),
    balance = join(folder, "balance.json");
  await writeFile(path, JSON.stringify(film));
  const at = film.segments[2].voice_start;
  const report = JSON.parse(
    execFileSync(
      process.execPath,
      [AUDIT_FRAMES, path, "0.5", "--from", String(at), "--to", String(at + 6)],
      {
        env: { ...process.env, TRACE: trace, MARKS: marks, BOUNDS: bounds, BALANCE: balance },
        encoding: "utf8",
      },
    ),
  );
  assert.deepEqual(report.errors, []);
  assert.ok(report.frames_checked > 0);
  // Thoughts whose picture stands off the content centre at a reviewers' instant, with the instant and both offsets.
  assert.ok(report.off_centre && typeof report.off_centre === "object");
  for (const rows of Object.values(report.off_centre))
    assert.ok(rows.every((row) => /^\d\d\.\d+ (two|late) -?\d+%\/-?\d+%$/.test(row)));
  // Containers that stood under half filled through more than a second of speech, with their kind, box, run and fill.
  assert.ok(report.underfilled_containers && typeof report.underfilled_containers === "object");
  for (const runs of Object.values(report.underfilled_containers))
    assert.ok(runs.every((run) => /^(frame|bracket) [\d,-]+ [\d.]+-[\d.]+ \d+%$/.test(run)));
  // Thoughts whose lit picture covers too little of the band, and names that repeat their caption or run past two lines.
  for (const key of ["thin_lit", "caption_echoes", "long_names", "sparse_runs"])
    assert.ok(report[key] && typeof report[key] === "object", key);
  // Runs of speech whose visible marks cover too little of the band, with their span and least cover.
  for (const runs of Object.values(report.sparse_runs))
    assert.ok(runs.every((run) => /^[\d.]+-[\d.]+ [\d.]+%$/.test(run)));
  for (const rows of Object.values(report.thin_lit))
    assert.ok(rows.every((row) => /^\d\d\.\d+ (two|late) [\d.]+%$/.test(row)));
  for (const rows of [...Object.values(report.caption_echoes), ...Object.values(report.long_names)])
    assert.ok(rows.every((row) => /@[\d.]+$/.test(row)));
  // Each thought instant in the stretch with its lit offsets and its share of the band.
  const instants = JSON.parse(await readFile(balance, "utf8"));
  assert.ok(
    instants.length > 0 &&
      instants.every(
        (v) => /^\d\d\.\d+$/.test(v.thought) && ["two", "late"].includes(v.at) && v.cover >= 0,
      ),
  );
  const rows = (await readFile(trace, "utf8"))
    .trim()
    .split("\n")
    .map((line) => line.split("\t"));
  assert.ok(
    rows.length > 0 && rows.every((row) => row.length === 5 && Number.isFinite(Number(row[2]))),
  );
  // Each firm mark of a voiced frame: its time, scene, box and whether a legible name stands at it.
  const marked = (await readFile(marks, "utf8"))
    .trim()
    .split("\n")
    .map((line) => line.split("\t"));
  assert.ok(
    marked.length > 0 &&
      marked.every(
        (row) =>
          row.length === 7 &&
          row.slice(2, 6).every((v) => Number.isInteger(Number(v))) &&
          ["0", "1"].includes(row[6]),
      ),
  );
  assert.ok(marked.some((row) => row[6] === "1"));
  // Each speaking scene's painted extent, within what the scene ever drew, and its mean share of the frame.
  const extents = JSON.parse(await readFile(bounds, "utf8"));
  assert.ok(Object.keys(extents).includes(film.segments[2].id));
  for (const { box, drawn, mean_frame_area } of Object.values(extents)) {
    assert.ok(box.every(Number.isInteger) && box[0] < box[2] && box[1] < box[3]);
    assert.ok(drawn[0] <= box[0] && drawn[1] <= box[1] && drawn[2] >= box[2] && drawn[3] >= box[3]);
    assert.ok(mean_frame_area > 0 && mean_frame_area <= 1);
  }
});

const segment = (x0, y0, x1, y1) => ({
  box: [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)],
  segs: [
    [
      [x0, y0],
      [x1, y1],
    ],
  ],
  kind: "open",
  frame: false,
});
const ringAt = (x, y, r) => {
  const points = Array.from({ length: 13 }, (_, k) => [
    x + r * Math.cos((k * Math.PI) / 6),
    y + r * Math.sin((k * Math.PI) / 6),
  ]);
  return {
    box: [x - r, y - r, x + r, y + r],
    segs: points.slice(1).map((point, k) => [points[k], point]),
    kind: "closed",
    frame: false,
  };
};
const seatRows = (rows) => rows.map((row) => [row.box.map(Math.round).join(","), row.named]);

test("each member repeated on a named rail waits for its own name", () => {
  const rail = segment(300, 500, 1300, 500),
    stations = [500, 800, 1100].map((x) => ringAt(x, 500, 20));
  const railName = { bounds: [300, 440, 420, 470] },
    firstName = { bounds: [470, 540, 530, 562] };
  const rows = seatMarks([rail, ...stations], [railName, firstName], [railName, firstName]);
  assert.deepEqual(seatRows(rows.filter((row) => row.member)), [
    ["480,480,520,520", true],
    ["780,480,820,520", false],
    ["1080,480,1120,520", false],
  ]);
  assert.ok(rows.some((row) => !row.member && row.named));
});

test("a repeated icon is one member, however many parts draw it", () => {
  const person = (x) => [ringAt(x, 480, 12), segment(x - 20, 500, x + 20, 500)],
    shapes = [...person(500), ...person(800)],
    first = { bounds: [470, 515, 530, 535] },
    second = { bounds: [770, 515, 830, 535] };
  assert.deepEqual(seatRows(seatMarks(shapes, [first, second], [first, second])), [
    ["480,468,520,500", true],
    ["780,468,820,500", true],
  ]);
  assert.deepEqual(seatRows(seatMarks(shapes, [first], [first])), [
    ["480,468,520,500", true],
    ["780,468,820,500", false],
  ]);
});

test("a station is one member: its disc's fill and outline, and the figure drawn on it", () => {
  const station = (x) => [
      { box: [x - 36, 424, x + 36, 496], segs: null, kind: "fill", frame: false },
      { ...ringAt(x, 460, 36), box: [x - 36, 424, x + 36, 496] },
      { box: [x - 11, 442, x + 11, 464], segs: null, kind: "fill", frame: false },
      segment(x - 16, 476, x + 16, 476),
    ],
    shapes = [...station(500), ...station(800)],
    names = [{ bounds: [450, 536, 550, 566] }, { bounds: [750, 536, 850, 566] }];
  assert.deepEqual(seatRows(seatMarks(shapes, names, names)), [
    ["464,424,536,496", true],
    ["764,424,836,496", true],
  ]);
});

test("nine repeated shapes are a texture, such as a gear's teeth, not a list", () => {
  const teeth = Array.from({ length: 9 }, (_, k) => segment(400 + k * 40, 500, 400 + k * 40, 524)),
    gear = { bounds: [400, 540, 520, 570] };
  assert.deepEqual(
    seatMarks(teeth, [gear], [gear]).filter((row) => row.member),
    [],
  );
});

test("a panel that holds only its corner marks waits whatever name stands beside it", () => {
  const record = { box: [700, 300, 1500, 700], segs: null, kind: "fill", frame: true },
    fold = segment(1478, 300, 1478, 322),
    beside = { bounds: [700, 710, 900, 735] };
  assert.deepEqual(seatRows(seatMarks([record, fold], [beside], [beside])), [
    ["700,300,1500,700", false],
  ]);
  const row = segment(760, 420, 1400, 420);
  assert.equal(seatMarks([record, fold, row], [beside], [beside])[0].named, true);
});

test("a frame holding only its title is filled by a sliver of its interior, and grows full as its members arrive", () => {
  const frame = { box: [100, 100, 500, 400], segs: null, kind: "fill", frame: true },
    title = { bounds: [120, 120, 380, 146] };
  const [only] = containerFill([frame], [title], [title]);
  assert.equal(only.kind, "frame");
  assert.deepEqual(only.box, [100, 100, 500, 400]);
  // The title covers 260 by 26 px of the 372 by 272 px interior inside the frame's edge band.
  assert.ok(Math.abs(only.fill - (260 * 26) / (372 * 272)) < 1e-9);
  const rows = { box: [130, 160, 470, 380], segs: null, kind: "fill", frame: false };
  assert.ok(containerFill([frame, rows], [title], [title])[0].fill > 0.5);
});

test("a bracket is filled by what stands on its open side along its spine", () => {
  // "[" with 30 px ticks pointing right and a 400 px spine.
  const bracket = {
    box: [170, 100, 200, 500],
    segs: [
      [
        [200, 100],
        [170, 100],
      ],
      [
        [170, 100],
        [170, 500],
      ],
      [
        [170, 500],
        [200, 500],
      ],
    ],
    kind: "open",
    frame: false,
  };
  const first = { bounds: [220, 120, 400, 160] },
    behind = { bounds: [20, 120, 150, 480] };
  const [one] = containerFill([bracket], [first, behind], [first, behind]);
  assert.equal(one.kind, "bracket");
  assert.ok(Math.abs(one.fill - 40 / 400) < 1e-9);
  const all = [first, { bounds: [220, 160, 400, 490] }];
  assert.ok(containerFill([bracket], all, all)[0].fill > 0.9);
  // A plain line is no container.
  assert.deepEqual(containerFill([segment(100, 100, 900, 100)], [first], [first]), []);
});

test("the motion audit summarises marks across frames and traces them to their scene", async () => {
  const film = await authoredTimeline("en"),
    folder = await scratchFolder();
  const path = join(folder, "timeline.json"),
    out = join(folder, "motion.json");
  await writeFile(path, JSON.stringify(film));
  const at = film.segments[5].voice_start;
  const summary = JSON.parse(
    execFileSync(
      process.execPath,
      [AUDIT_MOTION, path, "10", "--from", String(at), "--to", String(at + 8), "--out", out],
      { encoding: "utf8" },
    ),
  );
  assert.equal(summary.fps, 10);
  const report = JSON.parse(await readFile(out, "utf8"));
  assert.ok(Array.isArray(report.colour_snaps) && Array.isArray(report.still));
  assert.ok(
    report.colour_snaps.every((snap) => snap.origin === null || /^film\.js:\d+$/.test(snap.origin)),
  );
});

// A malformed invocation must stop with exit code 2 and the usage, never print a report of no frames.
const GEOMETRY = fileURLToPath(
  new URL("../../src/ddwg_film/picture/geometry-check.mjs", import.meta.url),
);
const invoke = (tool, args) => spawnSync(process.execPath, [tool, ...args], { encoding: "utf8" });
function assertRefused(tool, args, usage) {
  const result = invoke(tool, args);
  assert.equal(result.status, 2, `${args.join(" ")}: ${result.stderr}`);
  assert.equal(result.stdout, "", args.join(" "));
  assert.ok(result.stderr.includes(usage), args.join(" "));
}

test("the headless audits take their documented invocations, a step omitted before its flags included", async () => {
  const folder = await scratchFolder(),
    path = join(folder, "timeline.json");
  await writeFile(path, JSON.stringify(await authoredTimeline("zh")));
  const frames = JSON.parse(
    execFileSync(process.execPath, [AUDIT_FRAMES, path, "--from", "10", "--to", "12"], {
      encoding: "utf8",
    }),
  );
  assert.equal(frames.frames_checked, 8);
  const probe = JSON.parse(
    execFileSync(process.execPath, [AUDIT_FRAMES, path, "--at", "11"], { encoding: "utf8" }),
  );
  assert.ok(probe.texts.length > 0 && Array.isArray(probe.strokes));
  const motion = JSON.parse(
    execFileSync(process.execPath, [AUDIT_MOTION, path, "--from", "10", "--to", "11"], {
      encoding: "utf8",
    }),
  );
  assert.deepEqual([motion.fps, motion.frames, motion.range], [30, 30, [10, 11]]);
});

test("the headless audits refuse a malformed invocation", async () => {
  const folder = await scratchFolder(),
    path = join(folder, "timeline.json");
  await writeFile(path, JSON.stringify(await authoredTimeline("zh")));
  const frames = "Usage: node src/ddwg_film/picture/frame-audit.mjs";
  for (const args of [
    [],
    [path, "0"],
    [path, "abc"],
    [path, "0.25", "extra"],
    [path, "0.25", "--step", "1"],
    [path, "--from"],
    [path, "--from", "10", "--to", "10"],
    [path, "--from", "", "--to", "12"],
    [path, "--at", "never"],
    [path, "--at", "11", "--from", "10"],
  ])
    assertRefused(AUDIT_FRAMES, args, frames);
  const motion = "Usage: node src/ddwg_film/picture/motion-audit.mjs";
  for (const args of [
    [],
    [path, "0"],
    [path, "fast"],
    [path, "30", "--bogus"],
    [path, "30", "--from", "5", "--to", "4"],
    [path, "30", "--from", "1.02", "--to", "1.025"],
    [path, "30", "--out"],
  ])
    assertRefused(AUDIT_MOTION, args, motion);
});

test("the geometry check refuses a malformed invocation before opening a browser", () => {
  const usage = "Usage: node src/ddwg_film/picture/geometry-check.mjs";
  for (const args of [
    [],
    ["stage"],
    ["stage", "receipt.json", "0"],
    ["stage", "r", "1.5"],
    ["--bogus"],
  ])
    assertRefused(GEOMETRY, args, usage);
});

test("a picture's offset from the content centre is a share of the frame, as the reviewers measure it", () => {
  // The content band runs from 120 to 900 px, so its centre stands at (960, 510).
  assert.deepEqual(pictureOffset([760, 310, 1160, 710]), [0, 0]);
  // A rail alone in the top quarter stands a fifth of the frame's height above the centre.
  const [dx, dy] = pictureOffset([400, 250, 1520, 330]);
  assert.equal(dx, 0);
  assert.ok(Math.abs(dy - -220 / 1080) < 1e-12);
  // A panel on the right half stands 440 px, 23% of the width, right of the centre.
  assert.ok(Math.abs(pictureOffset([1100, 400, 1700, 620])[0] - 440 / 1920) < 1e-12);
});

test("a mark is lit as the reviewers' gray frame shows it, a thin stroke at its worst share of a cell", () => {
  const lit = litLevel({ ground: "#0F1519" });
  // A 2 px rail in the line colour can straddle two cells and stay below gray 48 (round 16's 30.5 rail measured 44-46),
  // so it never balances a picture; at 3 px, or in the muted colour, it is lit wherever it falls.
  assert.equal(lit("#63758B", 1, strokeShare(2)), false);
  assert.equal(lit("#63758B", 1, strokeShare(3)), true);
  assert.equal(lit("#9BA8B1", 1, strokeShare(2)), true);
  // A row fill is never lit; a 9 px dot in the evidence colour is, unless it has faded.
  assert.equal(lit("#1E2932", 1, fillShare([0, 0, 400, 300])), false);
  assert.equal(lit("#7DB7D8", 1, fillShare([0, 0, 9, 9])), true);
  assert.equal(lit("#7DB7D8", 0.15, fillShare([0, 0, 9, 9])), false);
  // A style other than a colour lifts nothing.
  assert.equal(lit("rgba(255,255,255,1)", 1), false);
});

test("a picture's cover is its box's share of the content band", () => {
  // The band runs from 120 to 900 px over the full width; a box reaching past it counts only its part inside.
  assert.equal(bandCover([0, 120, 1920, 900]), 1);
  assert.ok(Math.abs(bandCover([0, 0, 960, 510]) - 0.25) < 1e-12);
});

test("an arc samples the sweep a canvas draws, in the stand-in and the page instrumentation", () => {
  // A canvas draws arc(x, y, r, Math.PI, 0) clockwise through the top, the lock's shackle; drawn anticlockwise
  // from 0 to Math.PI it also passes the top. Every sampled point then stands at or above the centre.
  const above = (subs) => subs.flat().every(([, y]) => y <= 100 + 1e-9);
  const paints = [],
    ctx = canvasStandIn((paint) => paints.push(paint));
  for (const args of [
    [100, 100, 10, Math.PI, 0],
    [100, 100, 10, 0, Math.PI, true],
  ]) {
    ctx.beginPath();
    ctx.arc(...args);
    ctx.stroke();
  }
  assert.equal(paints.length, 2);
  assert.ok(paints.every((paint) => above(paint.subs)));
  // The page instrumentation wraps a context whose methods are the stand-in's, as in the browser.
  class CanvasRenderingContext2D {}
  const inner = canvasStandIn(() => {});
  for (const name of Object.keys(inner))
    CanvasRenderingContext2D.prototype[name] = (...args) => inner[name](...args);
  for (const key of ["globalAlpha", "lineWidth", "strokeStyle", "fillStyle"])
    Object.defineProperty(CanvasRenderingContext2D.prototype, key, { get: () => inner[key] });
  const window = {},
    context = vm.createContext({
      window,
      document: { getElementById: () => ({ dataset: { width: "1920" } }) },
      CanvasRenderingContext2D,
    });
  vm.runInContext(`(${instrument})()`, context);
  const page = new CanvasRenderingContext2D();
  page.beginPath();
  page.arc(100, 100, 10, Math.PI, 0);
  page.stroke();
  assert.equal(window.__paintedShapes.length, 1);
  assert.ok(above(window.__paintedShapes[0].subs));
  // A whole turn stays a whole turn, and a reversed span below one turn is brought into it.
  assert.equal(canvasSweep(0, 2 * Math.PI), 2 * Math.PI);
  assert.equal(canvasSweep(Math.PI, 0), Math.PI);
  assert.equal(canvasSweep(0, Math.PI, true), -Math.PI);
});

/* Chinese labels break where their author could break them: after a list mark or a connective. A name with no such
 * joint inside its width is authored as explicit lines instead, so no line begins inside a word. */
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
