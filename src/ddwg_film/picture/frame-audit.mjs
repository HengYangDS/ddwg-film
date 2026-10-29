/* Exercise every frame of the composition headlessly on one timeline and report layout, legibility and pacing.
 * Usage: node src/ddwg_film/picture/frame-audit.mjs <timeline.json> [step-seconds] [--from s] [--to s] [--at s]
 * --from and --to limit the frames exercised to one stretch of the film, such as the scenes being rebuilt; --at
 * reports one frame in detail. TRACE=<file> writes the label trace that ddwg_film.picture.sync_audit reads; MARKS=<file> writes the
 * firm marks and repeated members of each voiced frame, with whether a legible name stands at each, for its seat
 * check (src/ddwg_film/picture/seat-marks.mjs); BOUNDS=<file> writes each scene's drawn extent; BALANCE=<file> writes
 * each thought's lit offsets and band cover at the reviewers' two instants. The headless canvas
 * approximates text metrics (headless-composition.mjs); geometry-check.mjs measures real geometry. */
import { writeFileSync } from "node:fs";
import { parseArgs } from "node:util";

import {
  analysis,
  BALANCE_BAND,
  BALANCE_LIMITS,
  bandCover,
  COVER_LIMITS,
  faintLabels,
  fillShare,
  inkLevel,
  listTracker,
  litLevel,
  nameRules,
  pictureOffset,
  readingLoad,
  strokeShare,
} from "./geometry-check.mjs";
import { openComposition, readTimeline } from "./headless-composition.mjs";
import { containerFill, FRAME, seatMarks } from "./seat-marks.mjs";

const USAGE =
  "Usage: node src/ddwg_film/picture/frame-audit.mjs <timeline.json> [step-seconds] [--from s] [--to s] [--at s]";
/* A malformed invocation stops before any frame is exercised, so it can never read as a clean report. */
function refuse(problem) {
  console.error(`${problem}\n${USAGE}`);
  process.exit(2);
}
const seconds = (text, name) => {
  const value = text.trim() ? Number(text) : NaN;
  if (!Number.isFinite(value)) refuse(`${name} is not a number of seconds: ${text}`);
  return value;
};
let values, positionals;
try {
  ({ values, positionals } = parseArgs({
    allowPositionals: true,
    options: { from: { type: "string" }, to: { type: "string" }, at: { type: "string" } },
  }));
} catch (error) {
  refuse(error.message);
}
if (positionals.length < 1 || positionals.length > 2)
  refuse("Expected one timeline and at most one step");
const timeline = readTimeline(positionals[0]);
const step = seconds(positionals[1] ?? "0.25", "The step");
if (step <= 0) refuse(`The step is not a positive number of seconds: ${positionals[1]}`);
const probe = values.at === undefined ? null : seconds(values.at, "--at");
if (probe !== null && (values.from !== undefined || values.to !== undefined))
  refuse("--at reports one frame and takes no --from or --to");
const from = Math.max(
    0,
    Math.floor((values.from === undefined ? 0 : seconds(values.from, "--from")) / step) * step,
  ),
  to = Math.min(
    values.to === undefined ? timeline.duration : seconds(values.to, "--to"),
    timeline.duration,
  );
if (probe === null && !(from < to)) refuse(`The range from ${from} s to ${to} s holds no frame`);

/* Dim marks still collide visually: anything above 15% opacity is checked. */
const VISIBLE = 0.15;
/* Any paint above 4% opacity counts as ink, so a frame without it reads as bare ground. */
const INK = 0.04,
  STRONG = 0.25;
/* A mark's level is how far its brightest channel rises above the ground at its opacity. Within the voiced film no
 * frame may fall below 30 levels (steady scenes reach 150-225), and a chapter's first word needs 90. */
const LEVEL = 30,
  FIRST_WORD = 90;
/* Marks of the head band (the running head and the Illustrative chip) frame the picture rather than show it, so they
 * never keep a frame from reading as bare ground. */
const HEAD = 108;
const inHead = (points) => points.length > 0 && points.every(([, y]) => y < HEAD);
/* Each thought's picture, the union of its firm marks and legible names, is balanced on the content centre (within 8%
 * of the safe width and height) and fills at least half the safe width or two fifths of its height. */
const CENTRE = [960, 500],
  OFF = [0.08 * 1728, 0.08 * 972],
  FILL = [0.5 * 1728, 0.4 * 972];
/* The content band between the head band (top 10%) and the caption band (bottom 12%), and the smallest share of the
 * frame a thought's picture may cover two seconds in and 70% through. */
const BAND = [108, 950],
  AREA = 0.1;

const spanOf = (points) => [
  Math.min(...points.map((v) => v[0])),
  Math.min(...points.map((v) => v[1])),
  Math.max(...points.map((v) => v[0])),
  Math.max(...points.map((v) => v[1])),
];
/* The points a graphic covers: the corners of a fill's box, or every sampled point of a stroke. */
const pointsOf = (g) =>
  g.kind === "fill"
    ? [
        [g.box[0], g.box[1]],
        [g.box[2], g.box[3]],
      ]
    : g.subs.flat();
const emptyBox = () => [Infinity, Infinity, -Infinity, -Infinity];
const growBox = (box, [x, y]) => {
  box[0] = Math.min(box[0], x);
  box[1] = Math.min(box[1], y);
  box[2] = Math.max(box[2], x);
  box[3] = Math.max(box[3], y);
};
/* A measure holds runs of frames per key: the frame at t extends the last run, or starts one after a gap. */
function extendRun(runs, key, t) {
  const list = runs.get(key) ?? [];
  const last = list.at(-1);
  if (last && Math.abs(last[1] - t) < step * 1.5) last[1] = +(t + step).toFixed(2);
  else list.push([+t.toFixed(2), +(t + step).toFixed(2)]);
  runs.set(key, list);
}

const film = openComposition(timeline);
/* Reading load is measured as WCAG contrast against the ground: a label of at least 3:1 is legible; a label held
 * between 1.8:1 and 3:1 for more than a second is neither a usable recap nor gone, so it reads as faint clutter. The
 * ink level and the label, name and list rules are those of the real-browser check (geometry-check.mjs). */
const contrast = readingLoad(film.palette),
  levelOf = inkLevel(film.palette),
  isLit = litLevel(film.palette),
  inspectFrame = analysis(levelOf),
  nameFindings = nameRules(),
  lists = listTracker(),
  faintSeen = faintLabels();

/* Painted paths are recorded so labels crossing strokes or partly covered by fills are reported, and what the scene
 * itself paints outside the head band is counted, so speech over an empty picture is reported. */
let paints;
function onPaint(paint) {
  const points = paint.subs.flat(),
    seq = ++paints.seq;
  if (paint.kind === "text") paints.texts.push(seq);
  if (paint.scene && !inHead(points)) {
    paints.level = Math.max(paints.level, levelOf(paint.color, paint.alpha));
    if (paint.alpha > INK) paints.ink++;
    if (paint.alpha > STRONG) paints.strong++;
  }
  if (paint.kind === "stroke" && paint.alpha > VISIBLE)
    paints.graphics.push({
      kind: "stroke",
      seq,
      alpha: paint.alpha,
      color: paint.color,
      width: paint.lineWidth * paint.scale,
      subs: paint.subs,
      scene: paint.scene,
    });
  else if (paint.kind === "fill" && points.length)
    paints.graphics.push({
      kind: "fill",
      seq,
      alpha: paint.alpha,
      color: paint.color,
      box: spanOf(points),
      scene: paint.scene,
    });
}
const layoutScene = (t) => timeline.segments.findLast((v) => v.start <= t)?.id;
const units = (v) => v.replace(/[^\p{L}\p{N}]/gu, "").toLowerCase();
const thoughts = timeline.segments.flatMap((seg) => {
  let k = 0;
  return seg.utterance_groups.map((group, index) => {
    const need = units(group).length,
      first = k;
    let n = 0;
    while (k < seg.words.length && n < need) n += units(seg.words[k++].text).length;
    return {
      scene: seg.id,
      index: index + 1,
      start: seg.words[first].start,
      end: seg.words[k - 1].end,
      box: null,
    };
  });
});

/* Render the frame at t and gather what the measures read: its layout and graphics, what its scene painted, where it
 * falls in the timeline and its scene words. */
function renderedFrame(t) {
  paints = { graphics: [], texts: [], seq: 0, ink: 0, strong: 0, level: 0 };
  const layout = film.render(t, onPaint);
  const segments = timeline.segments,
    at = segments.findLastIndex((v) => v.start <= t),
    seg = segments[at],
    following = segments[at + 1];
  const speaking = segments.find((v) => v.voice_start <= t && t < v.voice_end);
  // A pause within a chapter: a scene that follows another of its chapter, until half a second into its voice, or a
  // scene whose voice has ended while the next one of its chapter waits.
  const inChapter = at > 0 && segments[at - 1].chapter === seg.chapter && t < seg.voice_start + 0.5;
  const beforeNext = following && following.chapter === seg.chapter && t > seg.voice_end;
  // Words are read; marks such as "?", "≠" or a bare value are seen, so only text with letters counts.
  const labels = layout.texts.filter((v) => v.scene && v.role === "label" && /\p{L}/u.test(v.text));
  // fillText order matches registration order, so each label knows what was painted before it.
  layout.texts.forEach((v, i) => {
    v.seq = paints.texts[i];
  });
  const sceneGraphics = paints.graphics.filter((g) => g.scene);
  return {
    t,
    layout,
    graphics: paints.graphics,
    sceneGraphics,
    sceneMarks: sceneGraphics.filter((g) => g.alpha > 0.35).length,
    sceneTexts: layout.texts.filter((v) => v.scene && v.alpha > 0.35).length,
    ink: paints.ink,
    strong: paints.strong,
    level: paints.level,
    speaking,
    seg,
    following,
    inChapter,
    beforeNext,
    // The scene a frame that must paint answers for: the speaking scene, or in a pause within a chapter the scene
    // just begun or the one about to begin.
    mustPaint: speaking ? speaking.id : inChapter ? seg.id : beforeNext ? following.id : null,
    labels,
    legible: labels.filter((v) => contrast(v.color, v.alpha) >= 3),
  };
}

const errors = new Map(),
  overlaps = new Map(),
  outside = new Map(),
  collisions = new Map(),
  shapesOutside = new Map(),
  empty = new Map(),
  blank = new Map(),
  bare = new Map(),
  thin = new Map(),
  dim = new Map(),
  firstWords = {},
  density = new Map(),
  clutter = [],
  trace = [],
  marks = [],
  extents = {},
  drawn = {};
/* The visual system's positive layout measures: names placed by hand, more than two text sizes or a dot-joined name at
 * once, a list whose names do not leave together, and a stage whose content stands off the content centre. */
const unplaced = new Map(),
  sizes = new Map(),
  dotJoins = new Map();

/* Within a chapter the picture should never empty between scenes, even in a pause: near-empty frames around a cut,
 * keyed by the incoming scene. */
function blankBetweenScenes(f) {
  if ((f.inChapter || f.beforeNext) && f.sceneMarks + f.sceneTexts < 2)
    extendRun(blank, f.inChapter ? f.seg.id : f.following.id, f.t);
}
/* Between the first and last voice no frame should be bare ground, in speech or in a pause within a chapter. */
function bareFrames(f) {
  if (f.mustPaint && !f.ink) extendRun(bare, f.mustPaint, f.t);
}
/* No voiced frame, and no pause within a chapter, may dim below the ground level a viewer reads as empty. */
function dimFrames(f) {
  if (f.mustPaint && f.level < LEVEL) extendRun(dim, f.mustPaint, f.t);
}
/* A chapter's first scene stands at half its contrast when the first word is spoken. */
function firstWordLevels(f) {
  const opener = timeline.segments.find(
    (v, i) =>
      i > 0 &&
      timeline.segments[i - 1].chapter !== v.chapter &&
      v.voice_start <= f.t &&
      f.t < v.voice_start + step,
  );
  if (opener) firstWords[opener.id] = Math.round(f.level);
}
/* Speech over a frame holding fewer than three firm marks (above 25%) from all scenes reads as nearly empty. */
function thinSpeech(f) {
  if (f.speaking && f.strong < 3) extendRun(thin, f.speaking.id, f.t);
}
/* Speech over fewer than two firm marks and words of its scene plays over an empty picture. */
function emptySpeech(f) {
  if (f.speaking && f.sceneMarks + f.sceneTexts < 2) extendRun(empty, f.speaking.id, f.t);
}
/* TRACE: each scene name of every frame, a placed name whole, with its contrast and opacity. */
function labelTrace(f) {
  for (const v of f.labels)
    trace.push(
      `${f.t.toFixed(2)}\t${v.scene}\t${contrast(v.color, v.alpha).toFixed(2)}\t${v.alpha.toFixed(3)}\t${v.whole ?? v.text}`,
    );
}
/* The firm graphics of the content band, each with its box, its kind and, for a stroke, its segments, as the seat
 * check and the container check read them (src/ddwg_film/picture/seat-marks.mjs). */
function bandShapes(f) {
  const shapes = [];
  const closed = (sub) =>
    sub.length > 2 && Math.hypot(sub[0][0] - sub.at(-1)[0], sub[0][1] - sub.at(-1)[1]) <= 2;
  // A frame is a filled panel or a closed outline at least FRAME in size.
  const large = (pts) => {
    const [x0, y0, x1, y1] = spanOf(pts);
    return x1 - x0 >= FRAME[0] && y1 - y0 >= FRAME[1];
  };
  for (const g of f.sceneGraphics) {
    if (g.alpha <= 0.35) continue;
    const pts = pointsOf(g);
    if (!pts.length) continue;
    const box = spanOf(pts);
    if (box[3] < BAND[0] || box[1] > BAND[1]) continue;
    const segs =
      g.kind === "fill" ? null : g.subs.flatMap((sub) => sub.slice(1).map((q, k) => [sub[k], q]));
    const frame = g.kind === "fill" ? large(pts) : g.subs.some((sub) => closed(sub) && large(sub));
    const kind = g.kind === "fill" ? "fill" : g.subs.some(closed) ? "closed" : "open";
    shapes.push({ box, segs, kind, frame });
  }
  return shapes;
}
const writtenOf = (f) => f.layout.texts.filter((v) => v.scene && v.alpha > 0.35);
/* MARKS: the seat check's marks of each voiced frame, with whether a legible name stands at each. */
function seats(f) {
  if (!f.speaking) return;
  for (const row of seatMarks(bandShapes(f), writtenOf(f), f.legible))
    marks.push(
      `${f.t.toFixed(3)}\t${f.speaking.id}\t${row.box.map(Math.round).join("\t")}\t${row.named ? 1 : 0}`,
    );
}
/* Containers: a group's frame or bracket whose contents fill less than half of it while it stands through more than a
 * second of speech fills in like a form; a container grows with its members instead. Runs are kept per container, by its kind
 * and its box to 4 px, and end when it leaves, fills or the speech pauses. */
const UNDERFILLED = 0.5,
  FORM_SECONDS = 1;
/* A container that holds a group: any bracket, or a frame of at least 60,000 px², about 300 by 200; smaller frames are
 * cards and icons whose glyph need not fill them. */
const GROUP_AREA = 60000;
const holdsGroup = (row) =>
  row.kind === "bracket" || (row.box[2] - row.box[0]) * (row.box[3] - row.box[1]) >= GROUP_AREA;
const containerRuns = new Map(),
  underfilled = [];
function closeContainer(key) {
  const run = containerRuns.get(key);
  containerRuns.delete(key);
  if (run && run.frames * step > FORM_SECONDS) underfilled.push(run);
}
function containers(f) {
  const seen = new Set();
  if (f.speaking)
    for (const row of containerFill(bandShapes(f), writtenOf(f), f.legible)) {
      const box = row.box.map((v) => Math.round(v / 4) * 4),
        key = `${row.kind}:${box}`;
      if (row.fill >= UNDERFILLED || !holdsGroup(row) || seen.has(key)) continue;
      seen.add(key);
      const run = containerRuns.get(key) ?? {
        scene: f.speaking.id,
        kind: row.kind,
        box,
        start: f.t,
        frames: 0,
        least: 1,
      };
      run.frames++;
      run.end = f.t + step;
      run.least = Math.min(run.least, row.fill);
      containerRuns.set(key, run);
    }
  for (const key of [...containerRuns.keys()]) if (!seen.has(key)) closeContainer(key);
}
/* A list's names are followed in every frame of their scene, voiced or not, so a name that leaves early is seen,
 * and the last frame a list is seen keeps its levels, so a list that leaves with part of it dimmed is seen. */
function listSets(f) {
  lists.see(f.labels, f.t, contrast);
}
/* Reading load counts names: a wrapped or growing name, or a term with its qualifier, is one name. */
function nameLoad(f) {
  if (!f.speaking) return;
  const found = nameFindings(f.labels, contrast);
  const entry = density.get(f.speaking.id) ?? { frames: 0, crowded: 0, peak: 0 };
  entry.frames++;
  if (found.some((v) => v.kind === "name_load")) entry.crowded++;
  entry.peak = Math.max(entry.peak, found.names);
  density.set(f.speaking.id, entry);
  const note = (map, key, value) => map.set(key, (map.get(key) ?? new Set()).add(value));
  for (const v of found) {
    if (v.kind === "unplaced_label") note(unplaced, v.scene, v.text);
    else if (v.kind === "dot_join") note(dotJoins, v.scene, v.text);
    else if (v.kind === "type_sizes") for (const size of v.sizes) note(sizes, f.speaking.id, size);
  }
}
/* Every lit point of the frame, as the reviewers' gray frame shows it: lit strokes and fills at their worst share of a
 * cell, and lit text, whose glyph strokes cover about half of a cell. */
const TEXT_SHARE = 0.5;
const litPoints = (f) => [
  ...f.graphics
    .filter((g) =>
      isLit(g.color, g.alpha, g.kind === "fill" ? fillShare(g.box) : strokeShare(g.width)),
    )
    .flatMap(pointsOf),
  ...f.layout.texts
    .filter((v) => isLit(v.color, v.alpha, TEXT_SHARE))
    .flatMap((v) => [
      [v.bounds[0], v.bounds[1]],
      [v.bounds[2], v.bounds[3]],
    ]),
];
/* Composition: the extent of the scene's firm marks and legible names stays balanced on the content centre, and at
 * the reviewers' instants, two seconds into each thought and 70% through it, the box around the firm marks and legible
 * names of the content band (the head band and the caption band excluded) covers a share of the frame, and the box
 * around every lit mark and legible name of the reviewers' band stands within their limits of its centre. */
function pictureBalance(f) {
  if (!f.speaking) return;
  // The head band's marks (the running head and the Illustrative chip) frame the picture rather than show it.
  const firm = f.sceneGraphics
      .filter((g) => g.alpha > 0.35 && !inHead(pointsOf(g)))
      .flatMap(pointsOf),
    named = f.legible
      .filter((v) => v.bounds[3] >= HEAD)
      .flatMap((v) => [
        [v.bounds[0], v.bounds[1]],
        [v.bounds[2], v.bounds[3]],
      ]);
  const picture = emptyBox();
  for (const point of [...firm, ...named]) growBox(picture, point);
  const thought = thoughts.find((v) => v.start <= f.t && f.t <= v.end);
  if (thought)
    for (const [name, at] of [
      ["two", thought.start + 2],
      ["late", thought.start + 0.7 * (thought.end - thought.start)],
    ]) {
      if (!(f.t <= at && at < f.t + step) || at > thought.end) continue;
      const band = emptyBox();
      for (const point of [...firm, ...named])
        if (!(point[1] < BAND[0] || point[1] > BAND[1])) growBox(band, point);
      (thought.areas ??= {})[name] =
        band[2] > band[0] ? ((band[2] - band[0]) * (band[3] - band[1])) / (1920 * 1080) : 0;
      const lit = emptyBox();
      for (const point of litPoints(f))
        if (point[1] >= BALANCE_BAND[0] && point[1] <= BALANCE_BAND[1]) growBox(lit, point);
      (thought.covers ??= {})[name] = lit[2] > lit[0] ? bandCover(lit) : 0;
      if (lit[2] > lit[0]) (thought.offsets ??= {})[name] = pictureOffset(lit);
    }
  if (thought && picture[2] > picture[0]) {
    thought.box ??= emptyBox();
    growBox(thought.box, [picture[0], picture[1]]);
    growBox(thought.box, [picture[2], picture[3]]);
  }
}
/* Sparse runs, as the Chinese review measured them: the box around every mark of visible ink in the content band,
 * through each voiced frame; a run of 1.5 s or more of speech whose box covers less than 4% of the band is reported per
 * scene, with its start, end and least cover. On the delivered round-16 film, the review's runs (18.2, 21.4, 16.2,
 * 14.1, 07.1, 12.5 and 25.8) appear when visible ink is 45 levels above the ground in the 480x270 gray frame; a thin
 * stroke counts at its worst share of a cell. */
const VISIBLE_LIFT = 45,
  SPARSE_COVER = 0.04,
  SPARSE_SECONDS = 1.5,
  isVisible = litLevel(film.palette, { lift: VISIBLE_LIFT });
const sparseRuns = [];
let sparseRun = null;
function sparseSpeech(f) {
  const box = emptyBox();
  if (f.speaking) {
    const points = [
      ...f.graphics
        .filter((g) =>
          isVisible(g.color, g.alpha, g.kind === "fill" ? fillShare(g.box) : strokeShare(g.width)),
        )
        .flatMap(pointsOf),
      ...f.layout.texts
        .filter((v) => v.role !== "caption" && isVisible(v.color, v.alpha, TEXT_SHARE))
        .flatMap((v) => [
          [v.bounds[0], v.bounds[1]],
          [v.bounds[2], v.bounds[3]],
        ]),
    ];
    for (const point of points)
      if (point[1] >= BALANCE_BAND[0] && point[1] <= BALANCE_BAND[1]) growBox(box, point);
  }
  const cover = box[2] > box[0] ? bandCover(box) : 0;
  if (f.speaking && cover < SPARSE_COVER) {
    if (
      sparseRun &&
      Math.abs(sparseRun.end - f.t) < step * 1.5 &&
      sparseRun.scene === f.speaking.id
    ) {
      sparseRun.end = f.t + step;
      sparseRun.least = Math.min(sparseRun.least, cover);
    } else {
      closeSparse();
      sparseRun = { scene: f.speaking.id, start: f.t, end: f.t + step, least: cover };
    }
  } else closeSparse();
}
function closeSparse() {
  if (sparseRun && sparseRun.end - sparseRun.start >= SPARSE_SECONDS) sparseRuns.push(sparseRun);
  sparseRun = null;
}
/* Names the eye reads while the ear hears them: a name that repeats the caption standing with it, at least three
 * quarters of the caption's letters; and names set on more than two lines. Each is kept per scene with the first time
 * it was seen. */
const echoes = new Map(),
  longNames = new Map();
function labelEchoes(f) {
  if (!f.speaking) return;
  const caption = f.layout.texts.find((v) => v.role === "caption" && v.alpha > 0.5),
    said = caption ? units(caption.text) : "",
    lines = new Map();
  for (const v of f.legible) {
    const key = `${v.scene}\u0000${v.whole ?? v.text}`,
      ys = lines.get(key) ?? new Set();
    ys.add(Math.round((v.bounds[1] + v.bounds[3]) / 2));
    lines.set(key, ys);
  }
  for (const [key, ys] of lines) {
    const whole = key.split("\u0000")[1],
      name = units(whole);
    if (ys.size > 2 && !longNames.has(key)) longNames.set(key, +f.t.toFixed(2));
    if (
      said &&
      name &&
      said.includes(name) &&
      name.length >= 0.75 * said.length &&
      !echoes.has(key)
    )
      echoes.set(key, +f.t.toFixed(2));
  }
}
/* Labels held between 1.8:1 and 3:1 for more than a second. */
function faintClutter(f) {
  for (const run of faintSeen(f.labels, f.t, contrast))
    clutter.push({
      key: `${run.scene}|${run.text}`,
      start: +run.start.toFixed(2),
      end: +run.end.toFixed(2),
    });
}
/* The marks and labels the frame's scene paints above 15% opacity, each with its scene and the points it covers. */
const visibleOf = (f) => [
  ...f.sceneGraphics.filter((g) => g.alpha > VISIBLE).map((g) => [g.scene, pointsOf(g)]),
  ...f.layout.texts
    .filter((v) => v.scene && v.alpha > VISIBLE)
    .map((v) => [
      v.scene,
      [
        [v.bounds[0], v.bounds[1]],
        [v.bounds[2], v.bounds[3]],
      ],
    ]),
];
/* BOUNDS: every frame a scene is drawn contributes its painted extent, so a scale keeps all of it in frame; each
 * speaking scene's extent and its mean share of the frame are kept for scale planning, from its own paints only, since
 * the outgoing scene holds over the first syllables of the next until the cut. */
function paintedExtent(f) {
  const visible = visibleOf(f);
  for (const [scene, points] of visible) {
    drawn[scene] ??= emptyBox();
    for (const point of points) growBox(drawn[scene], point);
  }
  if (!f.speaking) return;
  const e = (extents[f.speaking.id] ??= { box: emptyBox(), frames: 0, area: 0 }),
    frame = emptyBox();
  for (const [scene, points] of visible)
    if (scene === f.speaking.id) for (const point of points) growBox(frame, point);
  if (frame[2] > frame[0]) {
    growBox(e.box, [frame[0], frame[1]]);
    growBox(e.box, [frame[2], frame[3]]);
    e.frames++;
    e.area += ((frame[2] - frame[0]) * (frame[3] - frame[1])) / (1920 * 1080);
  }
}
/* The label and shape rules of the real-browser check: labels apart, inside the safe area and clear of shapes, and
 * shapes inside the action-safe area, each kept with the first frame and the evidence it was seen with. */
function labelsAndShapes(f) {
  const t = +f.t.toFixed(2);
  for (const v of inspectFrame(f.layout.texts, f.graphics)) {
    if (v.kind === "outside_safe_area") {
      const key = `${v.scene}:${v.text}`;
      if (!outside.has(key)) outside.set(key, { t, bounds: v.bounds.map(Math.round) });
    } else if (v.kind === "label_overlap") {
      const key = `${v.scene}:${v.pair.join("|")}`;
      if (!overlaps.has(key)) overlaps.set(key, t);
    } else if (v.kind.endsWith("_collision")) {
      const key = `${v.scene}:${v.text}|${v.shape}`;
      if (!collisions.has(key))
        collisions.set(key, {
          t,
          text: v.bounds.map(Math.round),
          graphic: v.graphic.map(Math.round),
        });
    } else if (v.kind.endsWith("_outside_action_safe")) {
      const key = `${layoutScene(f.t)}:${v.shape}`;
      if (!shapesOutside.has(key)) shapesOutside.set(key, { t, point: v.point.map(Math.round) });
    }
  }
}

/* What each frame is measured for; the trace, the marks and the bounds only when their file is asked for. */
const measures = [
  blankBetweenScenes,
  bareFrames,
  dimFrames,
  firstWordLevels,
  thinSpeech,
  emptySpeech,
  ...(process.env.TRACE ? [labelTrace] : []),
  ...(process.env.MARKS ? [seats] : []),
  listSets,
  nameLoad,
  pictureBalance,
  containers,
  labelEchoes,
  sparseSpeech,
  faintClutter,
  ...(process.env.BOUNDS ? [paintedExtent] : []),
  labelsAndShapes,
];
function* frameTimes() {
  if (probe !== null) yield probe;
  else for (let t = from; t < to; t += step) yield t;
}
let frame;
for (const t of frameTimes()) {
  try {
    frame = renderedFrame(t);
  } catch (error) {
    // The frame reported in detail must render; a stretch of the film reports each failure once.
    if (probe !== null) throw error;
    const key = String(error.message);
    if (!errors.has(key)) errors.set(key, t);
    continue;
  }
  for (const measure of measures) measure(frame);
}
for (const key of [...containerRuns.keys()]) closeContainer(key);
closeSparse();
if (probe !== null) {
  console.log(
    JSON.stringify(
      {
        texts: frame.layout.texts.map((v) => ({
          text: v.text,
          alpha: +v.alpha.toFixed(2),
          bounds: v.bounds.map(Math.round),
          seq: v.seq,
        })),
        strokes: frame.graphics
          .filter((g) => g.kind === "stroke")
          .map((g) => ({
            seq: g.seq,
            alpha: +g.alpha.toFixed(2),
            pts: g.subs.map((v) => [v[0], v.at(-1)].map((p) => p.map(Math.round))),
          })),
      },
      null,
      0,
    ),
  );
  process.exit(0);
}
const listsLeft = Object.groupBy(lists.findings(), (v) =>
  v.kind === "list_leaving_early" ? "early" : "dimmed",
);
const report = {
  frames_checked: Math.ceil((to - from) / step),
  errors: [...errors].map(([message, t]) => ({ message, t: +t.toFixed(2) })),
  overlaps: [...overlaps].map(([pair, t]) => ({ pair, t })),
  outside_safe_area: [...outside].map(([text, v]) => ({ text, ...v })),
  graphic_collisions: [...collisions].map(([pair, v]) => ({ pair, ...v })),
  empty_during_speech: Object.fromEntries(
    [...empty]
      .map(([id, runs]) => [id, runs.filter(([a, b]) => b - a > 0.5)])
      .filter(([, runs]) => runs.length),
  ),
  /* Near-empty frames longer than 0.15 s around a cut within a chapter, keyed by the incoming scene. */
  blank_between_scenes: Object.fromEntries(
    [...blank]
      .map(([id, runs]) => [id, runs.filter(([a, b]) => b - a > 0.15)])
      .filter(([, runs]) => runs.length),
  ),
  /* Every frame of bare ground (no scene paint above 4%) within the voiced film, keyed by the speaking or incoming scene;
   * the real-browser gate refuses even one. */
  bare_frames: Object.fromEntries([...bare].filter(([, runs]) => runs.length)),
  /* Every voiced frame, or frame in a pause within a chapter, whose brightest scene mark rises less than 30 levels
   * above the ground, keyed by the speaking or incoming scene. */
  dim_frames: Object.fromEntries([...dim].filter(([, runs]) => runs.length)),
  /* Chapter openers whose first scene shows less than 90 levels on the first word. */
  faint_first_words: Object.fromEntries(
    Object.entries(firstWords).filter(([, v]) => v < FIRST_WORD),
  ),
  /* Voiced runs longer than 0.1 s with fewer than three firm marks from all scenes, keyed by the speaking scene. */
  thin_during_speech: Object.fromEntries(
    [...thin]
      .map(([id, runs]) => [id, runs.filter(([a, b]) => b - a > 0.1)])
      .filter(([, runs]) => runs.length),
  ),
  shapes_outside_action_safe: [...shapesOutside].map(([key, v]) => ({ key, ...v })),
  /* Voiced frames with more than twelve names of at least 3:1 contrast, a wrapped or growing name counted once; none
   * may exceed it. DENSITY_ALL=1 lists every scene's peak. */
  name_load: Object.fromEntries(
    [...density]
      .map(([id, v]) => [id, { crowded: +(v.crowded / v.frames).toFixed(2), peak: v.peak }])
      .filter(([, v]) => process.env.DENSITY_ALL || v.crowded > 0),
  ),
  /* Legible names that no layout primitive placed, per scene. */
  unplaced_labels: Object.fromEntries(
    [...unplaced].map(([id, set]) => [id, [...set].slice(0, 12)]),
  ),
  /* Scenes showing more than two text sizes at once, with the sizes seen. */
  type_sizes: Object.fromEntries(
    [...sizes].map(([id, set]) => [id, [...set].sort((a, b) => a - b)]),
  ),
  /* Names that join items with a middle dot instead of a structure. */
  dot_joins: Object.fromEntries([...dotJoins].map(([id, set]) => [id, [...set]])),
  /* Lists whose names do not leave together: names that stop being legible more than 0.6 s before the last of their set. */
  lists_leaving_early: Object.fromEntries(
    Object.entries(Object.groupBy(listsLeft.early ?? [], (v) => `${v.scene}:${v.set}`)).map(
      ([key, names]) => [key, names.map((v) => `${v.name}@${v.at.toFixed(1)}`)],
    ),
  ),
  /* Lists that leave with part of the set dimmed: in the last frame the list is seen, a name below 90% of the
   * brightest name of its set in the same colour (a refused name is muted by design). A list leaves whole. */
  lists_leaving_dimmed: Object.fromEntries(
    Object.entries(Object.groupBy(listsLeft.dimmed ?? [], (v) => `${v.scene}:${v.set}`)).map(
      ([key, names]) => [
        key,
        `${names[0].at.toFixed(2)}: ${names.map((v) => `${v.name} ${v.share.toFixed(2)}`).join(", ")}`,
      ],
    ),
  ),
  /* Thoughts whose picture stands off the content centre or fills too little of the frame, with its centre and size. */
  off_balance: Object.fromEntries(
    Object.entries(
      Object.groupBy(
        thoughts
          .filter((v) => v.box)
          .map((v) => {
            const [x0, y0, x1, y1] = v.box,
              cx = (x0 + x1) / 2,
              cy = (y0 + y1) / 2,
              w = x1 - x0,
              h = y1 - y0;
            const off = Math.abs(cx - CENTRE[0]) > OFF[0] || Math.abs(cy - CENTRE[1]) > OFF[1],
              small = w < FILL[0] && h < FILL[1];
            return off || small
              ? {
                  scene: v.scene,
                  at: `${v.scene}.${v.index}`,
                  centre: [Math.round(cx), Math.round(cy)],
                  size: [Math.round(w), Math.round(h)],
                }
              : null;
          })
          .filter(Boolean),
        (v) => v.scene,
      ),
    ).map(([id, list]) => [id, list.map((v) => `${v.at}@${v.centre}:${v.size.join("x")}`)]),
  ),
  /* Thoughts whose picture stands beyond the reviewers' limit off the content centre at one of their instants, with the
   * instant and the offsets as percentages of the frame's width and height. */
  off_centre: Object.fromEntries(
    Object.entries(
      Object.groupBy(
        thoughts.flatMap((v) =>
          Object.entries(v.offsets ?? {})
            .filter(
              ([name, [dx, dy]]) => Math.max(Math.abs(dx), Math.abs(dy)) > BALANCE_LIMITS[name],
            )
            .map(([name, [dx, dy]]) => ({
              scene: v.scene,
              row: `${v.scene}.${v.index} ${name} ${Math.round(dx * 100)}%/${Math.round(dy * 100)}%`,
            })),
        ),
        (v) => v.scene,
      ),
    ).map(([id, list]) => [id, list.map((v) => v.row)]),
  ),
  /* Names equal to the caption standing with them, or sentence-long names it contains, per scene, with when each was
   * first seen; and names set on more than two lines. */
  caption_echoes: Object.fromEntries(
    Object.entries(Object.groupBy([...echoes], ([key]) => key.split("\u0000")[0])).map(
      ([id, list]) => [id, list.map(([key, t]) => `${key.split("\u0000")[1]}@${t}`)],
    ),
  ),
  long_names: Object.fromEntries(
    Object.entries(Object.groupBy([...longNames], ([key]) => key.split("\u0000")[0])).map(
      ([id, list]) => [id, list.map(([key, t]) => `${key.split("\u0000")[1]}@${t}`)],
    ),
  ),
  /* Runs of 1.5 s or more of speech whose visible marks cover under 4% of the content band, per scene. */
  sparse_runs: Object.fromEntries(
    Object.entries(Object.groupBy(sparseRuns, (v) => v.scene)).map(([id, runs]) => [
      id,
      runs.map((v) => `${v.start.toFixed(2)}-${v.end.toFixed(2)} ${(v.least * 100).toFixed(1)}%`),
    ]),
  ),
  /* Thoughts whose lit picture covers less than the reviewers' share of the band at one of their instants, with the
   * instant and the share. */
  thin_lit: Object.fromEntries(
    Object.entries(
      Object.groupBy(
        thoughts.flatMap((v) =>
          Object.entries(v.covers ?? {})
            .filter(([name, cover]) => cover < COVER_LIMITS[name])
            .map(([name, cover]) => ({
              scene: v.scene,
              row: `${v.scene}.${v.index} ${name} ${(cover * 100).toFixed(1)}%`,
            })),
        ),
        (v) => v.scene,
      ),
    ).map(([id, list]) => [id, list.map((v) => v.row)]),
  ),
  /* Containers that stood less than half filled through more than a second of speech, per scene: the kind, the box, the
   * run and its least fill. */
  underfilled_containers: Object.fromEntries(
    Object.entries(Object.groupBy(underfilled, (v) => v.scene)).map(([id, runs]) => [
      id,
      runs.map(
        (v) =>
          `${v.kind} ${v.box.join(",")} ${v.start.toFixed(2)}-${v.end.toFixed(2)} ${Math.round(v.least * 100)}%`,
      ),
    ]),
  ),
  /* Thoughts whose picture covers less than a tenth of the frame two seconds in or 70% through, with both shares, and
   * the median shares over all thoughts. */
  sparse_beats: (() => {
    const rows = thoughts.filter((v) => v.areas),
      med = (k) => {
        const a = rows
          .map((v) => v.areas[k])
          .filter((v) => v !== undefined)
          .sort((p, q) => p - q);
        return a.length ? +a[a.length >> 1].toFixed(3) : null;
      };
    return {
      median_two: med("two"),
      median_late: med("late"),
      thoughts: rows
        .filter((v) => (v.areas.two ?? 1) < AREA || (v.areas.late ?? 1) < AREA)
        .map(
          (v) =>
            `${v.scene}.${v.index}@${(v.areas.two ?? NaN).toFixed(3)}/${(v.areas.late ?? NaN).toFixed(3)}`,
        ),
    };
  })(),
  /* Labels held between 1.8:1 and 3:1 for more than a second, per scene: total seconds and the longest runs. */
  faint_clutter: Object.fromEntries(
    Object.entries(Object.groupBy(clutter, (v) => v.key.split("|")[0])).map(([id, runs]) => [
      id,
      {
        seconds: +runs.reduce((n, v) => n + v.end - v.start, 0).toFixed(1),
        longest: runs.sort((a, b) => b.end - b.start - (a.end - a.start)).slice(0, 3),
      },
    ]),
  ),
};
if (process.env.TRACE) writeFileSync(process.env.TRACE, trace.join("\n") + "\n");
if (process.env.BALANCE)
  writeFileSync(
    process.env.BALANCE,
    JSON.stringify(
      thoughts.flatMap((v) =>
        Object.entries(v.covers ?? {}).map(([at, cover]) => ({
          thought: `${v.scene}.${v.index}`,
          at,
          dx: v.offsets?.[at] ? +(v.offsets[at][0] * 100).toFixed(1) : null,
          dy: v.offsets?.[at] ? +(v.offsets[at][1] * 100).toFixed(1) : null,
          cover: +(cover * 100).toFixed(1),
        })),
      ),
    ) + "\n",
  );
if (process.env.MARKS) writeFileSync(process.env.MARKS, marks.join("\n") + "\n");
if (process.env.BOUNDS)
  writeFileSync(
    process.env.BOUNDS,
    JSON.stringify(
      Object.fromEntries(
        Object.entries(extents).map(([id, e]) => [
          id,
          {
            box: e.box.map(Math.round),
            drawn: (drawn[id] ?? []).map(Math.round),
            mean_frame_area: +(e.area / Math.max(1, e.frames)).toFixed(3),
          },
        ]),
      ),
      null,
      1,
    ) + "\n",
  );
console.log(JSON.stringify(report, null, 1));
process.exitCode = report.errors.length ? 1 : 0;
