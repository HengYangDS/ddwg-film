/** Run the composition headlessly in Node, as the staged document runs it, for the frame and motion audits.
 *
 * film.js runs in its own vm context on a canvas stand-in. Each stroke, fill and text it paints while the caller renders
 * a frame reaches the caller as one paint: its kind, the scene drawing it (film.js publishes window.__sceneId around each
 * scene), its opacity and colour, its line width and the scale of its transform, and its geometry twice over. `subs`
 * is the path as screen subpaths, sampled the way the real-browser check samples them (geometry-check.mjs); a text
 * stands at its anchor. `points` are the drawing points in the painter's own coordinates, as the motion audit
 * identifies a mark across frames: an arc gives the corners of its circle, a text the corners of its box, and
 * `toScreen` maps them to the screen. The stand-in estimates text metrics; geometry-check.mjs measures real ones. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const COMPOSITION = fileURLToPath(new URL("../../../picture/film.js", import.meta.url));

/** The timeline as staging hands it to the composition: the edition of its language and no render offset, unless
 * the timeline gives them. */
export function readTimeline(path) {
  const authored = JSON.parse(readFileSync(path, "utf8"));
  return {
    ...authored,
    edition: authored.edition ?? { Chinese: "zh", English: "en" }[authored.language],
    render_offset: authored.render_offset ?? 0,
  };
}

const fontSize = (font) => Number(/(\d+(?:\.\d+)?)px/.exec(font)?.[1] ?? 30);
/* Estimated metrics: a CJK character is as wide as the font size, a capital 0.66 of it and any other character 0.54;
 * the box rises and falls from its baseline in proportion to the size. */
function textMetrics(text, { font, textAlign, textBaseline }) {
  const size = fontSize(font);
  const width = [...text].reduce(
    (w, ch) =>
      w +
      (/[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/u.test(ch)
        ? size
        : /[A-Z]/.test(ch)
          ? size * 0.66
          : size * 0.54),
    0,
  );
  const left = textAlign === "center" ? width / 2 : textAlign === "right" ? width : 0;
  const ascent = textBaseline === "top" ? 0 : textBaseline === "middle" ? size * 0.52 : size * 0.8;
  const descent =
    textBaseline === "top" ? size * 1.05 : textBaseline === "middle" ? size * 0.52 : size * 0.22;
  return {
    width,
    actualBoundingBoxLeft: left,
    actualBoundingBoxRight: width - left,
    actualBoundingBoxAscent: ascent,
    actualBoundingBoxDescent: descent,
  };
}

/* The drawing state a canvas saves and restores, as a fresh canvas starts it; film.js sets every property it uses. */
const STATE = {
  globalAlpha: 1,
  strokeStyle: "#000000",
  fillStyle: "#000000",
  lineWidth: 1,
  lineCap: "butt",
  lineJoin: "miter",
  font: "10px sans-serif",
  textAlign: "start",
  textBaseline: "alphabetic",
  letterSpacing: "0px",
};

/** The 2D context film.js draws on: exactly the members it uses, each refusing any other. `deliver` receives each
 * stroke, fill and text as a paint, called directly by the method painting it, so a paint can be traced into film.js.
 * fillRect lays the ground under each frame, which no audit counts as a mark, so it paints nothing. */
/** The signed angle a canvas arc sweeps from a0 toward a1: clockwise unless anticlockwise, a whole turn once the
 * angles span one, and otherwise the difference brought into one turn, as the HTML canvas specification draws it. */
export function canvasSweep(a0, a1, anticlockwise = false) {
  const turn = 2 * Math.PI,
    delta = anticlockwise ? a0 - a1 : a1 - a0,
    sweep = delta >= turn ? turn : ((delta % turn) + turn) % turn;
  return anticlockwise ? -sweep : sweep;
}

export function canvasStandIn(deliver) {
  let m = [1, 0, 0, 1, 0, 0],
    state = { ...STATE, dash: [] };
  const stack = [];
  // The current path twice over: screen subpaths as sampled, and the drawing points in the painter's coordinates.
  let subs = [],
    sub = null,
    last = [0, 0],
    points = [];
  const tx = (x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
  const begin = (pts) => {
    sub = pts;
    subs.push(sub);
  };
  const extend = (pts) => {
    if (!sub) begin(pts);
    else sub.push(...pts);
  };
  const mul = (a, b) => [
    a[0] * b[0] + a[2] * b[1],
    a[1] * b[0] + a[3] * b[1],
    a[0] * b[2] + a[2] * b[3],
    a[1] * b[2] + a[3] * b[3],
    a[0] * b[4] + a[2] * b[5] + a[4],
    a[1] * b[4] + a[3] * b[5] + a[5],
  ];
  // An arc or ellipse is sampled every 7.5 degrees, at least four steps, along the sweep a canvas draws: clockwise
  // from the start angle unless anticlockwise, through less than one turn unless the angles span a whole one. So
  // arc(x, y, r, Math.PI, 0) draws the upper half, not the lower one that a straight interpolation would give.
  const sampled = (x, y, rx, ry, rotation, a0, a1, anticlockwise = false) => {
    const sweep = canvasSweep(a0, a1, anticlockwise),
      n = Math.max(4, Math.ceil(Math.abs(sweep) / (Math.PI / 24))),
      pts = [];
    for (let i = 0; i <= n; i++) {
      const a = a0 + (sweep * i) / n,
        ex = rx * Math.cos(a),
        ey = ry * Math.sin(a);
      pts.push(
        tx(
          x + ex * Math.cos(rotation) - ey * Math.sin(rotation),
          y + ex * Math.sin(rotation) + ey * Math.cos(rotation),
        ),
      );
    }
    return pts;
  };
  // A paint carries the state it was painted in and its geometry: `subs` and `points`, and a text's own fields.
  const paintOf = (kind, color, geometry) => {
    const [a, b, c, d, e, f] = m;
    return {
      kind,
      alpha: state.globalAlpha,
      color,
      lineWidth: state.lineWidth,
      scale: Math.hypot(a, b),
      toScreen: ([x, y]) => [a * x + c * y + e, b * x + d * y + f],
      ...geometry,
    };
  };
  const path = () => ({ subs: subs.map((v) => v.slice()), points: points.slice() });
  const members = {
    setTransform(a, b, c, d, e, f) {
      m = [a, b, c, d, e, f];
    },
    getTransform: () => ({ a: m[0], b: m[1], c: m[2], d: m[3], e: m[4], f: m[5] }),
    translate(x, y) {
      m = mul(m, [1, 0, 0, 1, x, y]);
    },
    scale(x, y) {
      m = mul(m, [x, 0, 0, y, 0, 0]);
    },
    save() {
      stack.push([m, { ...state }]);
    },
    // As on a canvas, a restore without a saved state does nothing.
    restore() {
      if (stack.length) [m, state] = stack.pop();
    },
    setLineDash(segments) {
      state.dash = [...segments];
    },
    measureText: (v) => textMetrics(v, state),
    beginPath() {
      subs = [];
      sub = null;
      points = [];
    },
    moveTo(x, y) {
      begin([tx(x, y)]);
      last = [x, y];
      points.push([x, y]);
    },
    lineTo(x, y) {
      extend([tx(x, y)]);
      last = [x, y];
      points.push([x, y]);
    },
    closePath() {
      if (sub?.length) sub.push(sub[0]);
    },
    arc(x, y, r, a0, a1, anticlockwise = false) {
      extend(sampled(x, y, r, r, 0, a0, a1, anticlockwise));
      last = [x + r * Math.cos(a1), y + r * Math.sin(a1)];
      points.push([x - r, y - r], [x + r, y + r]);
    },
    ellipse(x, y, rx, ry, rotation, a0, a1, anticlockwise = false) {
      extend(sampled(x, y, rx, ry, rotation, a0, a1, anticlockwise));
      const ex = rx * Math.cos(a1),
        ey = ry * Math.sin(a1);
      last = [
        x + ex * Math.cos(rotation) - ey * Math.sin(rotation),
        y + ex * Math.sin(rotation) + ey * Math.cos(rotation),
      ];
      // Like an arc's circle, the whole ellipse spans the drawing points.
      const hx = Math.hypot(rx * Math.cos(rotation), ry * Math.sin(rotation)),
        hy = Math.hypot(rx * Math.sin(rotation), ry * Math.cos(rotation));
      points.push([x - hx, y - hy], [x + hx, y + hy]);
    },
    quadraticCurveTo(cx, cy, x, y) {
      const [x0, y0] = last,
        pts = [];
      for (let i = 1; i <= 12; i++) {
        const q = i / 12,
          u = 1 - q;
        pts.push(
          tx(u * u * x0 + 2 * u * q * cx + q * q * x, u * u * y0 + 2 * u * q * cy + q * q * y),
        );
      }
      extend(pts);
      last = [x, y];
      points.push([cx, cy], [x, y]);
    },
    roundRect(x, y, w, h) {
      begin([tx(x, y), tx(x + w, y), tx(x + w, y + h), tx(x, y + h), tx(x, y)]);
      sub = null;
      last = [x, y];
      points.push([x, y], [x + w, y + h]);
    },
    stroke() {
      deliver(paintOf("stroke", state.strokeStyle, path()));
    },
    fill() {
      deliver(paintOf("fill", state.fillStyle, path()));
    },
    fillText(v, x, y) {
      const text = String(v),
        k = textMetrics(text, state);
      deliver(
        paintOf("text", state.fillStyle, {
          subs: [[tx(x, y)]],
          points: [
            [x - k.actualBoundingBoxLeft, y - k.actualBoundingBoxAscent],
            [x + k.actualBoundingBoxRight, y + k.actualBoundingBoxDescent],
          ],
          text,
          size: fontSize(state.font),
        }),
      );
    },
    fillRect() {},
  };
  return new Proxy(members, {
    get(target, key) {
      if (Object.hasOwn(target, key)) return target[key];
      if (Object.hasOwn(STATE, key)) return state[key];
      // Symbols are how Node inspects a value; any other name is a member film.js does not use.
      if (typeof key === "symbol") return undefined;
      throw TypeError(`The headless canvas has no ${key}`);
    },
    set(target, key, value) {
      if (!Object.hasOwn(STATE, key))
        throw TypeError(`The headless canvas has no ${String(key)} to set`);
      state[key] = value;
      return true;
    },
  });
}

/** Load film.js on `timeline`. Returns `palette`, the film's colours; `render(t, onPaint)`, which renders the frame
 * at t, hands each of its paints to `onPaint` and returns the layout film.js publishes; `camera(segment, t)`, the
 * film's own camera of a segment at t; and `origin()`, called while a paint is handed over, the innermost line of a
 * scene body in film.js that made it, as `film.js:<line>`, or null. */
export function openComposition(timeline) {
  const source = readFileSync(COMPOSITION, "utf8");
  // The scene whose body each line of film.js lies in, so a paint can be traced to the scene line that made it.
  const sceneOfLine = [];
  let open = null;
  for (const line of source.split("\n")) {
    open = /^scenes\["(\d+)"\] = function/.exec(line)?.[1] ?? open;
    sceneOfLine.push(open);
    if (line === "};") open = null;
  }
  const window = { FILM: timeline };
  // Paints reach the caller only while it renders a frame, not while film.js paints its first frame on loading.
  let onPaint = null;
  function deliver(paint) {
    if (!onPaint) return;
    paint.scene = window.__sceneId ?? null;
    onPaint(paint);
  }
  // The document holds the picture's canvas and the film element whose width sets the resolution, nothing else.
  const ctx = canvasStandIn(deliver);
  const elements = {
    picture: {
      getContext(type) {
        if (type !== "2d") throw TypeError(`The headless canvas has no ${type} context`);
        return ctx;
      },
    },
    film: { dataset: { width: "1920" } },
  };
  const context = vm.createContext({
    window,
    document: {
      getElementById(id) {
        if (!Object.hasOwn(elements, id)) throw TypeError(`The headless document has no #${id}`);
        return elements[id];
      },
    },
  });
  vm.runInContext(source, context, { filename: COMPOSITION });
  const palette = Object.freeze({ ...vm.runInContext("P", context) });
  let cameraOf;
  return {
    palette,
    render(t, paints = () => {}) {
      onPaint = paints;
      try {
        window.renderFrame(t);
      } finally {
        onPaint = null;
      }
      return window.__filmLayout;
    },
    camera(segment, t) {
      cameraOf ??= vm.runInContext('typeof cameraOf === "function" ? cameraOf : null', context);
      if (!cameraOf) throw Error("The composition defines no cameraOf");
      return cameraOf(segment, t);
    },
    origin() {
      // The whole stack below the paint: V8 keeps ten frames, fewer than a helper nested in a scene may need.
      const limit = Error.stackTraceLimit,
        trace = {};
      Error.stackTraceLimit = Infinity;
      Error.captureStackTrace(trace, deliver);
      Error.stackTraceLimit = limit;
      for (const match of trace.stack.matchAll(/film\.js:(\d+):\d+/g))
        if (sceneOfLine[Number(match[1]) - 1]) return `film.js:${match[1]}`;
      return null;
    },
  };
}
