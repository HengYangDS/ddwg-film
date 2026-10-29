/** Inspect painted Canvas labels and shapes with the real browser at native output frames. */
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

import { launchBrowser } from "./headless-browser.mjs";

/* The rules below are serialisable into the page: each factory is self-contained, takes the film's measures as
 * arguments and runs both in the real browser (inspectFilm) and headlessly (frame-audit.mjs). */

/** Ink level: how far a mark rises above the film's ground, its brightest channel's lift over the ground times its
 * opacity (0-255). A style other than a #rrggbb colour lifts nothing. */
export function inkLevel(palette) {
  const channels = (color) => [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
  const ground = channels(palette.ground);
  return function level(color, alpha) {
    return /^#[0-9a-f]{6}$/i.test(color ?? "")
      ? alpha * Math.max(...channels(color).map((v, k) => v - ground[k]))
      : 0;
  };
}

/** Reading load: the WCAG contrast of a mark's ink over the film's ground. A word of at least 3:1 is legible; a word
 * held between 1.8:1 and 3:1 is neither legible nor gone, so it reads as faint clutter. A style other than a #rrggbb
 * colour reads as the film's ink. */
export function readingLoad(palette) {
  const luminance = (rgb) => {
    const [r, g, b] = rgb.map((c) => {
      c /= 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const channels = (color) => [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
  const ground = channels(palette.ground),
    ink = channels(palette.ink),
    base = luminance(ground) + 0.05;
  return function contrast(color, alpha) {
    const rgb = /^#[0-9a-f]{6}$/i.test(color ?? "") ? channels(color) : ink;
    const blended = rgb.map((v, i) => alpha * v + (1 - alpha) * ground[i]);
    return (luminance(blended) + 0.05) / base;
  };
}

/** Balance as the reviewers measure it: the content band runs from 120 to 900 px, so a picture's box stands off the
 * content centre (960, 510) by these shares of the frame's width and height. A thought's picture may stand at most 12%
 * off two seconds into the thought and at most 8% off 70% through it, and its box must cover at least 5% and 10% of
 * the band at those instants. */
export const BALANCE_BAND = [120, 900],
  BALANCE_LIMITS = { two: 0.12, late: 0.08 },
  COVER_LIMITS = { two: 0.05, late: 0.1 };
export function pictureOffset([x0, y0, x1, y1]) {
  return [((x0 + x1) / 2 - 960) / 1920, ((y0 + y1) / 2 - 510) / 1080];
}
export function bandCover([x0, y0, x1, y1]) {
  const [top, bottom] = BALANCE_BAND;
  return (
    ((x1 - x0) * Math.max(0, Math.min(y1, bottom) - Math.max(y0, top))) / (1920 * (bottom - top))
  );
}

/** Lit marks, as the reviewers see them: each frame scaled to 480x270 gray, where a mark is lit if its pixels rise
 * above gray 48. A mark lifts a cell's gray by its luma over the ground's, times its opacity and its share of the
 * 4 px cell. A thin stroke can straddle two cells, so it is counted at its worst share: a 2 px line in the line colour
 * stays below gray 48 there (round 16's 30.5 rail measured 44-46), and a picture balanced only by such a line is not
 * balanced. A style other than a #rrggbb colour is never lit. With `lift`, a mark counts when it rises that many
 * levels above the ground instead. */
export const LIT_GRAY = 48;
export function litLevel(palette, { lift = null } = {}) {
  const luma = (color) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ground = luma(palette.ground),
    threshold = lift === null ? LIT_GRAY : ground + lift;
  return function lit(color, alpha, share = 1) {
    return (
      /^#[0-9a-f]{6}$/i.test(color ?? "") &&
      ground + (luma(color) - ground) * alpha * share > threshold
    );
  };
}
/* A stroke's worst share of a cell, and a fill's: thin marks fall short of a whole cell. */
export const strokeShare = (width) => Math.min(1, width / 7),
  fillShare = ([x0, y0, x1, y1]) => Math.min(1, (x1 - x0) / 7) * Math.min(1, (y1 - y0) / 7);

/** Frame analysis: labels must stay apart, inside the safe area, and clear of shapes; shapes stay inside the
 * action-safe area. Dim marks still collide visually, so anything above 15% opacity counts. A frame that must paint
 * (during speech, or in a pause within a chapter) may not show bare ground: the brightest mark of a scene, at its ink
 * `level` (inkLevel), must rise at least 30 levels above the ground (steady scenes reach 150-225), so no stage or scene
 * change dims through an empty picture; on a chapter's first word it must reach 90, half a steady scene. The frame's
 * brightest level is returned with its findings, so a run of speech that stays below 90 for half a second, a picture
 * of faint placeholders only, is reported too. Marks of the head band (the running head and the Illustrative chip)
 * frame the picture rather than show it, so they never keep a frame from reading as bare ground. Labels end at least
 * 34 px above the caption band. Each finding carries its evidence: a label's bounds, the overlapping pair, the shape
 * and the part of it that collides (a fill's box or a stroke's first crossing segment), or a shape's first point
 * outside the action-safe area. */
export function analysis(level) {
  const SAFE = [96, 40, 1824, 920],
    ACTION_SAFE = [96, 54, 1824, 1026],
    VISIBLE = 0.15,
    LEVEL = 30,
    FIRST_WORD = 90,
    HEAD = 108;
  const inHead = (points) => points.length > 0 && points.every(([, y]) => y < HEAD);
  const intersects = (a, b, pad = 2) =>
    a[0] < b[2] - pad && b[0] < a[2] - pad && a[1] < b[3] - pad && b[1] < a[3] - pad;
  const contains = (outer, inner, pad = 1) =>
    outer[0] <= inner[0] + pad &&
    outer[1] <= inner[1] + pad &&
    outer[2] >= inner[2] - pad &&
    outer[3] >= inner[3] - pad;
  /* Liang-Barsky: does segment p-q enter rectangle r? */
  const crosses = ([x0, y0], [x1, y1], [rx0, ry0, rx1, ry1]) => {
    let a = 0,
      b = 1;
    const dx = x1 - x0,
      dy = y1 - y0;
    for (const [p, q] of [
      [-dx, x0 - rx0],
      [dx, rx1 - x0],
      [-dy, y0 - ry0],
      [dy, ry1 - y0],
    ]) {
      if (p === 0) {
        if (q < 0) return false;
        continue;
      }
      const r = q / p;
      if (p < 0) {
        if (r > b) return false;
        if (r > a) a = r;
      } else {
        if (r < a) return false;
        if (r < b) b = r;
      }
    }
    return true;
  };
  // The first segment of a stroke that enters a zone, as its two end points.
  const crossing = (subs, zone) => {
    for (const v of subs) {
      const k = v.findIndex((p, k) => k > 0 && crosses(v[k - 1], p, zone));
      if (k > 0) return [...v[k - 1], ...v[k]];
    }
    return null;
  };
  const pointsOf = (g) =>
    g.kind === "fill"
      ? [
          [g.box[0], g.box[1]],
          [g.box[2], g.box[3]],
        ]
      : g.subs.flat();
  return function inspectFrame(
    texts,
    shapes,
    { mustPaint = false, firstWord = false, scene = null } = {},
  ) {
    const findings = [];
    const brightest = Math.max(
      0,
      ...texts
        .filter(
          (v) =>
            v.scene &&
            !inHead([
              [v.bounds[0], v.bounds[1]],
              [v.bounds[2], v.bounds[3]],
            ]),
        )
        .map((v) => level(v.color, v.alpha)),
      ...shapes.filter((g) => g.scene && !inHead(pointsOf(g))).map((g) => level(g.color, g.alpha)),
    );
    if (mustPaint && brightest < LEVEL) findings.push({ kind: "bare_ground", scene, text: "" });
    if (firstWord && brightest < FIRST_WORD)
      findings.push({ kind: "faint_first_word", scene, text: "" });
    findings.brightest = brightest;
    for (const g of shapes) {
      if (g.alpha <= VISIBLE) continue;
      const point = pointsOf(g).find(
        ([x, y]) =>
          x < ACTION_SAFE[0] - 0.5 ||
          y < ACTION_SAFE[1] - 0.5 ||
          x > ACTION_SAFE[2] + 0.5 ||
          y > ACTION_SAFE[3] + 0.5,
      );
      if (point)
        findings.push({
          kind: `${g.kind}_outside_action_safe`,
          scene: null,
          text: "",
          shape: g.kind,
          point,
        });
    }
    const labels = texts.filter((v) => v.alpha > VISIBLE);
    labels.forEach((a, i) => {
      const [x0, y0, x1, y1] = a.bounds;
      if (
        a.role !== "caption" &&
        a.role !== "title" &&
        (x0 < SAFE[0] || y0 < SAFE[1] || x1 > SAFE[2] || y1 > SAFE[3])
      ) {
        findings.push({
          kind: "outside_safe_area",
          scene: a.scene,
          text: a.text,
          bounds: a.bounds,
        });
      }
      if (a.role !== "caption") {
        // An opaque fill painted between a shape and the label (its pill or card) hides the shape beneath it.
        const covers = shapes.filter(
          (g) => g.kind === "fill" && g.alpha > 0.9 && g.seq < a.seq && contains(g.box, a.bounds),
        );
        for (const g of shapes) {
          if (g.alpha <= VISIBLE || covers.some((f) => f.seq > g.seq)) continue;
          const zone = [
            x0 + 3 - g.width / 2,
            y0 + 3 - g.width / 2,
            x1 - 3 + g.width / 2,
            y1 - 3 + g.width / 2,
          ];
          const graphic =
            g.kind === "fill"
              ? intersects(g.box, a.bounds, 3) && !contains(g.box, a.bounds)
                ? g.box
                : null
              : crossing(g.subs, zone);
          if (graphic)
            findings.push({
              kind: `label_${g.kind}_collision`,
              scene: a.scene,
              text: a.text,
              shape: g.kind,
              bounds: a.bounds,
              graphic,
            });
        }
      }
      for (const b of labels.slice(i + 1)) {
        if (intersects(a.bounds, b.bounds))
          findings.push({
            kind: "label_overlap",
            scene: a.scene ?? b.scene,
            text: `${a.text} | ${b.text}`,
            pair: [a.text, b.text],
          });
      }
    });
    return findings;
  };
}

/** Names: a voiced frame may show at most twelve legible names, the lines of a wrapped or growing name, or a term
 * with its qualifier, counting once; every legible name is placed by a layout primitive, names use at most two text
 * sizes, and no name joins items with a middle dot instead of a structure. The findings carry how many names are
 * legible, and a type-size finding the sizes shown. */
export function nameRules() {
  const LIMIT = 12;
  return function nameFindings(words, contrast) {
    const legible = words.filter((v) => contrast(v.color, v.alpha) >= 3),
      findings = [],
      scene = legible[0]?.scene ?? null;
    findings.names = new Set(legible.map((v) => `${v.scene}|${v.whole ?? v.text}`)).size;
    if (findings.names > LIMIT) findings.push({ kind: "name_load", scene, text: "" });
    for (const v of legible) {
      if (!v.placed) findings.push({ kind: "unplaced_label", scene: v.scene, text: v.text });
      if (/·/u.test(v.text)) findings.push({ kind: "dot_join", scene: v.scene, text: v.text });
    }
    const sizes = [...new Set(legible.map((v) => v.size))].sort((a, b) => a - b);
    if (sizes.length > 2)
      findings.push({ kind: "type_sizes", scene, text: sizes.join(","), sizes });
    return findings;
  };
}

/** Lists: the names of one list build and leave as a whole, so each stops being legible within 0.6 s of the last of
 * its list, and in the last frame the list is seen every name stands at no less than 90% of the brightest name of its
 * set in the same colour (a refused name is muted by design). Each finding names its list's set and the name, with
 * when it was last seen and, for a dimmed name, its share of that brightest name. */
export function listTracker() {
  const lists = new Map(),
    last = new Map();
  return {
    see(words, t, contrast) {
      const levels = new Map();
      for (const v of words) {
        if (!v.set || contrast(v.color, v.alpha) < 3) continue;
        const key = `${v.scene}\u0000${v.set}`,
          seen = lists.get(key) ?? new Map();
        seen.set(v.whole ?? v.text, t);
        lists.set(key, seen);
        const level = levels.get(key) ?? new Map(),
          name = `${v.color}\u0001${v.whole ?? v.text}`;
        level.set(name, Math.max(level.get(name) ?? 0, v.alpha));
        levels.set(key, level);
      }
      for (const [key, level] of levels) last.set(key, { t, level });
    },
    findings() {
      const early = [...lists].flatMap(([key, seen]) => {
        const end = Math.max(...seen.values()),
          [scene, set] = key.split("\u0000");
        return [...seen]
          .filter(([, at]) => at < end - 0.6)
          .map(([name, at]) => ({
            kind: "list_leaving_early",
            scene,
            text: `${set}: ${name}`,
            set,
            name,
            at,
          }));
      });
      const dimmed = [...last].flatMap(([key, { t, level }]) => {
        const [scene, set] = key.split("\u0000"),
          peak = new Map(),
          colour = (name) => name.split("\u0001")[0];
        for (const [name, alpha] of level)
          peak.set(colour(name), Math.max(peak.get(colour(name)) ?? 0, alpha));
        return [...level]
          .filter(([name, alpha]) => alpha < 0.9 * peak.get(colour(name)))
          .map(([name, alpha]) => ({
            kind: "list_leaving_dimmed",
            scene,
            text: `${set}: ${name.split("\u0001")[1]}`,
            set,
            name: name.split("\u0001")[1],
            at: t,
            share: alpha / peak.get(colour(name)),
          }));
      });
      return [...early, ...dimmed];
    },
  };
}

/** Faint labels: a word held between 1.8:1 and 3:1 for more than a second is neither a usable recap nor gone, so it
 * reads as faint clutter. Each frame's words are seen in turn; the faint runs that ended in it are returned, each with
 * its scene and text and the times it began and ended. */
export function faintLabels() {
  const faint = new Map();
  return function see(words, t, contrast) {
    const inBand = new Set(),
      ended = [];
    for (const v of words) {
      const c = contrast(v.color, v.alpha),
        key = `${v.scene}\u0000${v.text}`;
      if (c >= 1.8 && c < 3) {
        inBand.add(key);
        if (!faint.has(key)) faint.set(key, { scene: v.scene, text: v.text, start: t });
      }
    }
    for (const [key, run] of faint) {
      if (inBand.has(key)) continue;
      if (t - run.start > 1) ended.push({ ...run, end: t });
      faint.delete(key);
    }
    return ended;
  };
}

/** Page instrumentation: record every painted path and fill in logical frame coordinates. */
export function instrument() {
  const proto = CanvasRenderingContext2D.prototype;
  const state = new WeakMap();
  const shapes = (window.__paintedShapes = []);
  window.__paintedText = [];
  let seq = 0;
  const scale = () => Number(document.getElementById("film").dataset.width) / 1920;
  const of = (ctx) => {
    if (!state.has(ctx)) state.set(ctx, { subs: [], sub: null, last: [0, 0] });
    return state.get(ctx);
  };
  const point = (ctx, x, y) => {
    const m = ctx.getTransform(),
      s = scale();
    return [(m.a * x + m.c * y + m.e) / s, (m.b * x + m.d * y + m.f) / s];
  };
  const extend = (ctx, pts) => {
    const p = of(ctx);
    if (!p.sub) {
      p.sub = pts;
      p.subs.push(p.sub);
    } else p.sub.push(...pts);
  };
  const wrap = (name, record) => {
    const original = proto[name];
    proto[name] = function (...args) {
      record(this, ...args);
      return original.apply(this, args);
    };
  };
  window.__resetPaint = () => {
    shapes.length = 0;
    window.__paintedText.length = 0;
    seq = 0;
  };
  wrap("beginPath", (ctx) => {
    const p = of(ctx);
    p.subs = [];
    p.sub = null;
  });
  wrap("moveTo", (ctx, x, y) => {
    const p = of(ctx);
    p.sub = [point(ctx, x, y)];
    p.subs.push(p.sub);
    p.last = [x, y];
  });
  wrap("lineTo", (ctx, x, y) => {
    extend(ctx, [point(ctx, x, y)]);
    of(ctx).last = [x, y];
  });
  wrap("closePath", (ctx) => {
    const p = of(ctx);
    if (p.sub?.length) p.sub.push(p.sub[0]);
  });
  // The page code is serialised whole, so it carries its own copy of the canvas sweep that headless-composition.mjs
  // exports as canvasSweep: clockwise unless anticlockwise, a whole turn once the angles span one.
  const arcPoints = (ctx, x, y, rx, ry, rotation, a0, a1, anticlockwise = false) => {
    const turn = 2 * Math.PI,
      delta = anticlockwise ? a0 - a1 : a1 - a0,
      span = delta >= turn ? turn : ((delta % turn) + turn) % turn,
      sweep = anticlockwise ? -span : span,
      n = Math.max(4, Math.ceil(Math.abs(sweep) / (Math.PI / 24))),
      pts = [];
    for (let i = 0; i <= n; i++) {
      const a = a0 + (sweep * i) / n,
        ex = rx * Math.cos(a),
        ey = ry * Math.sin(a);
      pts.push(
        point(
          ctx,
          x + ex * Math.cos(rotation) - ey * Math.sin(rotation),
          y + ex * Math.sin(rotation) + ey * Math.cos(rotation),
        ),
      );
    }
    return pts;
  };
  wrap("arc", (ctx, x, y, r, a0, a1, anticlockwise) => {
    extend(ctx, arcPoints(ctx, x, y, r, r, 0, a0, a1, anticlockwise));
    of(ctx).last = [x + r * Math.cos(a1), y + r * Math.sin(a1)];
  });
  wrap("ellipse", (ctx, x, y, rx, ry, rotation, a0, a1, anticlockwise) => {
    extend(ctx, arcPoints(ctx, x, y, rx, ry, rotation, a0, a1, anticlockwise));
  });
  wrap("quadraticCurveTo", (ctx, cx, cy, x, y) => {
    const [x0, y0] = of(ctx).last,
      pts = [];
    for (let i = 1; i <= 12; i++) {
      const q = i / 12,
        u = 1 - q;
      pts.push(
        point(
          ctx,
          u * u * x0 + 2 * u * q * cx + q * q * x,
          u * u * y0 + 2 * u * q * cy + q * q * y,
        ),
      );
    }
    extend(ctx, pts);
    of(ctx).last = [x, y];
  });
  wrap("roundRect", (ctx, x, y, w, h) => {
    const p = of(ctx);
    p.subs.push([
      point(ctx, x, y),
      point(ctx, x + w, y),
      point(ctx, x + w, y + h),
      point(ctx, x, y + h),
      point(ctx, x, y),
    ]);
    p.sub = null;
    p.last = [x, y];
  });
  wrap("stroke", (ctx) => {
    const m = ctx.getTransform();
    shapes.push({
      kind: "stroke",
      seq: ++seq,
      alpha: ctx.globalAlpha,
      width: (ctx.lineWidth * Math.hypot(m.a, m.b)) / scale(),
      subs: of(ctx).subs.map((v) => v.slice()),
      color: typeof ctx.strokeStyle === "string" ? ctx.strokeStyle : null,
      scene: window.__sceneId ?? null,
    });
  });
  wrap("fill", (ctx) => {
    const pts = of(ctx).subs.flat();
    seq++;
    if (pts.length)
      shapes.push({
        kind: "fill",
        seq,
        alpha: ctx.globalAlpha,
        box: [
          Math.min(...pts.map((v) => v[0])),
          Math.min(...pts.map((v) => v[1])),
          Math.max(...pts.map((v) => v[0])),
          Math.max(...pts.map((v) => v[1])),
        ],
        color: typeof ctx.fillStyle === "string" ? ctx.fillStyle : null,
        scene: window.__sceneId ?? null,
      });
  });
  wrap("fillText", () => {
    window.__paintedText.push(++seq);
  });
}

/** The page program: render every `every`-th of `frames` frames at `rate` and collect each finding once, with the
 * first frame it was seen and how many frames show it. `rules` are the sources of the serialisable rules above and
 * `palette` the film's colours, from which the page derives its measures. */
export function inspectFilm(rules, palette, frames, every, rate) {
  const make = (name) => new Function(`return (${rules[name]})`)();
  const contrast = make("readingLoad")(palette),
    inspectFrame = make("analysis")(make("inkLevel")(palette)),
    nameFindings = make("nameRules")(),
    lists = make("listTracker")(),
    faintSeen = make("faintLabels")();
  const seen = new Map(),
    errors = new Map();
  // Speech whose brightest scene mark stays below 90 levels for half a second shows only faint placeholders.
  let dimSpeech = null;
  // A receipt keeps each finding's kind, scene and text; the evidence a finding carries is for the frame audit.
  const add = ({ kind, scene, text }, t) => {
    const key = `${kind}:${scene}:${text}`;
    const entry = seen.get(key) ?? { kind, scene, text, first: t, frames: 0 };
    entry.frames++;
    seen.set(key, entry);
  };
  let checked = 0;
  for (let frame = 0; frame < frames; frame += every) {
    const t = frame / rate,
      filmTime = t + (window.FILM.render_offset || 0);
    window.__resetPaint();
    try {
      window.renderFrame(t);
    } catch (error) {
      if (!errors.has(String(error))) errors.set(String(error), t);
      continue;
    }
    checked++;
    const texts = window.__filmLayout.texts.map((v, i) => ({
      ...v,
      seq: window.__paintedText[i],
    }));
    // A frame must paint while a voice speaks, and in a pause within a chapter once the next scene has begun.
    const segments = window.FILM.segments,
      at = segments.findLastIndex((v) => v.start <= filmTime),
      shown = segments[at];
    const speaking = segments.find((v) => v.voice_start <= filmTime && filmTime < v.voice_end);
    const between =
      at > 0 && segments[at - 1].chapter === shown.chapter && filmTime < shown.voice_start;
    // The checked frame that carries a chapter's first word: its first scene must already stand.
    const firstWord =
      at > 0 &&
      segments[at - 1].chapter !== shown.chapter &&
      shown.voice_start <= filmTime &&
      filmTime < shown.voice_start + every / rate;
    const context = {
      mustPaint: Boolean(speaking) || between,
      firstWord,
      scene: (speaking ?? shown)?.id ?? null,
    };
    const found = inspectFrame(texts, window.__paintedShapes, context);
    for (const finding of found) add(finding, t);
    if (speaking && found.brightest < 90) dimSpeech ??= { start: t, scene: speaking.id };
    else if (dimSpeech) {
      if (t - dimSpeech.start >= 0.5)
        add({ kind: "faint_during_speech", scene: dimSpeech.scene, text: "" }, dimSpeech.start);
      dimSpeech = null;
    }
    // Names: only scene words count; marks such as "?" or a bare value are seen rather than read.
    const words = texts.filter((v) => v.scene && v.role === "label" && /\p{L}/u.test(v.text));
    if (speaking) for (const finding of nameFindings(words, contrast)) add(finding, t);
    lists.see(words, t, contrast);
    for (const run of faintSeen(words, t, contrast))
      add({ kind: "faint_label", scene: run.scene, text: run.text }, run.start);
  }
  for (const finding of lists.findings()) add(finding, 0);
  return {
    checked,
    findings: [...seen.values()],
    errors: [...errors].map(([message, t]) => ({ message, t })),
  };
}

const RULES = { inkLevel, readingLoad, analysis, nameRules, listTracker, faintLabels };

export async function inspectWorkspace(workspace, { step = 2 } = {}) {
  const entry = resolve(workspace, "index.html");
  const source = await readFile(entry, "utf8");
  const attribute = (name) => Number(source.match(new RegExp(`data-${name}="([0-9.]+)"`))?.[1]);
  const [width, height, duration, fps] = ["width", "height", "duration", "fps"].map(attribute);
  if (![width, height, duration, fps].every(Number.isFinite))
    throw Error("Workspace does not declare its frame contract");
  const browser = await launchBrowser({
    args: ["--allow-file-access-from-files", "--no-sandbox"],
    defaultViewport: { width, height, deviceScaleFactor: 1 },
  });
  try {
    const page = await browser.newPage();
    await page.evaluateOnNewDocument(instrument);
    await page.goto(pathToFileURL(entry).href, { waitUntil: "load", timeout: 45000 });
    await page.evaluate(() => window.__filmReady);
    const result = await page.evaluate(
      inspectFilm,
      Object.fromEntries(Object.entries(RULES).map(([name, rule]) => [name, rule.toString()])),
      // The film's own palette, read where the film runs.
      await page.evaluate("P"),
      Math.round(duration * fps),
      step,
      fps,
    );
    return {
      width,
      height,
      duration,
      fps,
      step_frames: step,
      browser: await browser.version(),
      index_sha256: createHash("sha256").update(source).digest("hex"),
      ...result,
    };
  } finally {
    await browser.close();
  }
}

if (import.meta.main) {
  const USAGE =
    "Usage: node src/ddwg_film/picture/geometry-check.mjs <workspace> <receipt.json> [step-frames]";
  // A malformed invocation stops before the browser opens, so it can never write a passing receipt.
  const refuse = (problem) => {
    console.error(`${problem}\n${USAGE}`);
    process.exit(2);
  };
  let positionals = [];
  try {
    ({ positionals } = parseArgs({ allowPositionals: true }));
  } catch (error) {
    refuse(error.message);
  }
  const [workspace, receipt, every = "2"] = positionals;
  if (positionals.length < 2 || positionals.length > 3)
    refuse("Expected one workspace, one receipt and at most one step");
  const step = Number(every);
  if (!Number.isInteger(step) || step < 1)
    refuse(`The step is not a positive whole number of frames: ${every}`);
  const report = await inspectWorkspace(workspace, { step });
  const passed = report.errors.length === 0 && report.findings.length === 0;
  await writeFile(
    receipt,
    JSON.stringify(
      { format: "picture-geometry", workspace: resolve(workspace), passed, ...report },
      null,
      2,
    ) + "\n",
  );
  console.log(
    JSON.stringify({
      passed,
      frames_checked: report.checked,
      findings: report.findings.length,
      errors: report.errors.length,
    }),
  );
  process.exitCode = passed ? 0 : 1;
}
