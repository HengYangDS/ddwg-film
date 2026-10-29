/** The seat check's marks: whether a legible name stands at each firm mark of a voiced frame.
 *
 * A mark is the firm paint of the content band that touches (within 12 px, so a link that ends in its quiet point
 * belongs to the mark it reaches). A legible name names a mark in its place: a name within 60 px, a name in its row
 * within 240 px, or a name in its column within 90 px, the reaches of a name placed by its structure's rule. A frame is
 * a filled panel or a closed outline at least 120 by 100 px. A mark is an empty frame while nothing but its own edge
 * marks, such as a document's fold, lies inside its frames; an empty frame waits for its content whatever name stands
 * beside it. A mark that holds another mark or a name is not waiting, and a mark inside a named mark belongs to it.
 *
 * Members are judged on their own. Shapes of one kind repeated at one size that do not touch each other, such as the
 * stations of a rail, its stubs, ruled rows, slots or owner frames, each wait for their own name, whatever names the
 * container they stand on or in. Repeated shapes that touch draw one member while they stay the size of an icon, such
 * as a figure's head and shoulders, or paint one place, such as a disc's fill and outline; a member drawn inside a
 * smaller member is part of it, and a member stands in a list only while another member repeats one of its shapes. A
 * name names at most one member, the nearest it reaches, and a member that holds a name is named. */

export const MARK_JOIN = 12,
  NAME_REACH = 60,
  ROW_REACH = 240,
  COLUMN_REACH = 90,
  FRAME = [120, 100];
/* Marks this close to a frame's edge belong to the edge. */
const EDGE = 14;
/* Repeated shapes agree in width and height within 12% or 4 px. More than eight is a texture, such as a calendar's days
 * or a gear's teeth, not a list; a shape under 16 px is a detail of a mark, and an icon fits within 64 px. */
const SAME = 0.12,
  SAME_PX = 4,
  MOST_MEMBERS = 8,
  DETAIL = 16,
  ICON = 64;

const near = (a, b, d) =>
  a[0] - d <= b[2] && b[0] - d <= a[2] && a[1] - d <= b[3] && b[1] - d <= a[3];
const encloses = (outer, inner) =>
  outer[0] <= inner[0] && outer[1] <= inner[1] && outer[2] >= inner[2] && outer[3] >= inner[3];
const gap = (a, b) =>
  Math.hypot(Math.max(0, a[0] - b[2], b[0] - a[2]), Math.max(0, a[1] - b[3], b[1] - a[3]));
const places = (name, box) => {
  const dx = Math.max(0, box[0] - name[2], name[0] - box[2]),
    dy = Math.max(0, box[1] - name[3], name[1] - box[3]);
  return gap(box, name) <= NAME_REACH || (!dy && dx <= ROW_REACH) || (!dx && dy <= COLUMN_REACH);
};
/* Distances between painted segments and filled boxes, for marks whose paint touches. */
const toSegment = ([px, py], [[x0, y0], [x1, y1]]) => {
  const dx = x1 - x0,
    dy = y1 - y0,
    q =
      dx || dy
        ? Math.max(0, Math.min(1, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)))
        : 0;
  return Math.hypot(px - x0 - q * dx, py - y0 - q * dy);
};
const side = ([ax, ay], [bx, by], [cx, cy]) =>
  Math.sign((bx - ax) * (cy - ay) - (by - ay) * (cx - ax));
const segmentGap = (s, u) =>
  side(s[0], s[1], u[0]) * side(s[0], s[1], u[1]) < 0 &&
  side(u[0], u[1], s[0]) * side(u[0], u[1], s[1]) < 0
    ? 0
    : Math.min(toSegment(s[0], u), toSegment(s[1], u), toSegment(u[0], s), toSegment(u[1], s));
const edges = ([x0, y0, x1, y1]) => [
  [
    [x0, y0],
    [x1, y0],
  ],
  [
    [x1, y0],
    [x1, y1],
  ],
  [
    [x1, y1],
    [x0, y1],
  ],
  [
    [x0, y1],
    [x0, y0],
  ],
];
const inBox = ([x, y], b) => x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3];
function touches(a, b) {
  if (!near(a.box, b.box, MARK_JOIN)) return false;
  if (!a.segs && !b.segs) return true;
  const [stroke, other] = a.segs ? [a, b] : [b, a];
  const against = other.segs ?? edges(other.box);
  return stroke.segs.some(
    (s) =>
      (!other.segs && (inBox(s[0], other.box) || inBox(s[1], other.box))) ||
      against.some((u) => segmentGap(s, u) <= MARK_JOIN),
  );
}
const span = (boxes) => [
  Math.min(...boxes.map((b) => b[0])),
  Math.min(...boxes.map((b) => b[1])),
  Math.max(...boxes.map((b) => b[2])),
  Math.max(...boxes.map((b) => b[3])),
];
/* A shape lies inside a frame when its centre is beyond the frame's edge band and it is not the frame itself, such as
 * the outline drawn over a panel's fill. */
const inside = (shape, frame) => {
  const [x0, y0, x1, y1] = frame.box,
    b = shape.box,
    centre = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
  return (
    shape !== frame &&
    b.some((v, k) => Math.abs(v - frame.box[k]) > EDGE) &&
    inBox(centre, [x0 + EDGE, y0 + EDGE, x1 - EDGE, y1 - EDGE])
  );
};
const size = (b) => [b[2] - b[0], b[3] - b[1]];
const alike = (a, b) => {
  const [aw, ah] = size(a.box),
    [bw, bh] = size(b.box);
  return (
    a.kind === b.kind &&
    Math.abs(aw - bw) <= Math.max(SAME_PX, SAME * Math.max(aw, bw)) &&
    Math.abs(ah - bh) <= Math.max(SAME_PX, SAME * Math.max(ah, bh))
  );
};
const sameBox = (a, b) => a.every((v, k) => Math.abs(v - b[k]) <= 1);
/* Disjoint sets of n items: `find` names the set an item is in, `join` merges the first item's set into the second's,
 * and `groups` lists the items of each set, the sets in the order of their first item. */
function disjointSets(n) {
  const root = Array.from({ length: n }, (_, i) => i),
    find = (i) => (root[i] === i ? i : (root[i] = find(root[i])));
  return {
    find,
    join(i, j) {
      root[find(i)] = find(j);
    },
    groups(items) {
      const groups = new Map();
      items.forEach((item, i) => {
        const set = find(i);
        if (!groups.has(set)) groups.set(set, []);
        groups.get(set).push(item);
      });
      return [...groups.values()];
    },
  };
}
/* The groups of items joined by a relation, directly or through others. */
const connected = (items, linked) => {
  const sets = disjointSets(items.length);
  for (let i = 0; i < items.length; i++)
    for (let j = i + 1; j < items.length; j++) if (linked(items[i], items[j])) sets.join(i, j);
  return sets.groups(items);
};

/* A bracket is an open stroke of three straight runs: a spine at least as long as a frame is high between two ticks of
 * at most TICK px that turn to the same side, its open side. What stands on that side within REACH px fills it. */
const TICK = 48,
  REACH = 900;
/* The straight runs of a stroke: consecutive segments along one axis join, and segments under 3 px are corners. */
function runs(segs) {
  const out = [];
  for (const [[x0, y0], [x1, y1]] of segs) {
    if (Math.hypot(x1 - x0, y1 - y0) < 3) continue;
    const axis = Math.abs(x1 - x0) >= Math.abs(y1 - y0) ? 0 : 1,
      last = out.at(-1);
    if (last && last.axis === axis) last.to = [x1, y1];
    else out.push({ axis, from: [x0, y0], to: [x1, y1] });
  }
  return out;
}
/* A bracket's spine, along `axis` from `start` to `end` at `at` across it, and the side its ticks turn to. */
function bracketOf(shape) {
  if (shape.kind !== "open" || !shape.segs) return null;
  const parts = runs(shape.segs);
  if (parts.length !== 3) return null;
  const [first, spine, last] = parts,
    length = (run) => Math.abs(run.to[spine.axis] - run.from[spine.axis]),
    reach = (run) => Math.abs(run.to[1 - spine.axis] - run.from[1 - spine.axis]);
  if (first.axis === spine.axis || last.axis === spine.axis) return null;
  if (length(spine) < FRAME[1] || reach(first) > TICK || reach(last) > TICK) return null;
  const at = spine.from[1 - spine.axis],
    side = Math.sign(first.from[1 - spine.axis] - at);
  if (!side || side !== Math.sign(last.to[1 - spine.axis] - at)) return null;
  const ends = [spine.from[spine.axis], spine.to[spine.axis]];
  return { axis: spine.axis, start: Math.min(...ends), end: Math.max(...ends), at, side };
}
const area = (b) => Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);

/** Each container of a voiced frame with the share of it that its contents fill. A frame is filled by the box around
 * the marks and texts inside its edge band, as a share of that interior; a bracket by the part of its spine that the
 * marks and texts on its open side cover. `shapes`, `written` and `legible` are those of seatMarks. */
export function containerFill(shapes, written, legible) {
  const holders = [
    ...shapes.map((v) => ({ box: v.box, shape: v })),
    ...[...written, ...legible].map((v) => ({ box: v.bounds, shape: null })),
  ];
  const rows = [];
  for (const shape of shapes) {
    if (shape.frame) {
      const [x0, y0, x1, y1] = shape.box,
        interior = [x0 + EDGE, y0 + EDGE, x1 - EDGE, y1 - EDGE],
        held = holders.filter((v) => v.shape !== shape && encloses(interior, v.box));
      rows.push({
        kind: "frame",
        box: shape.box,
        fill: held.length ? area(span(held.map((v) => v.box))) / area(interior) : 0,
      });
      continue;
    }
    const spine = bracketOf(shape);
    if (!spine) continue;
    const { axis, start, end, at, side } = spine,
      across = 1 - axis,
      covered = holders
        .filter((v) => v.shape !== shape)
        .map((v) => v.box)
        .filter((b) => {
          const middle = (b[across] + b[across + 2]) / 2;
          return side * (middle - at) > 0 && side * (middle - at) <= REACH;
        })
        .map((b) => [Math.max(start, b[axis]), Math.min(end, b[axis + 2])])
        .filter(([a, b]) => b > a)
        .sort((p, q) => p[0] - q[0]);
    let length = 0,
      reached = start;
    for (const [a, b] of covered) {
      length += Math.max(0, b - Math.max(a, reached));
      reached = Math.max(reached, b);
    }
    rows.push({ kind: "bracket", box: shape.box, fill: length / (end - start) });
  }
  return rows;
}

/** Each mark and each member of a voiced frame with whether a legible name stands at it.
 * `shapes` are the firm graphics of the content band, each {box, segs, kind, frame}: segs are a stroke's segments
 * (null for a fill), kind is "fill", "closed" or "open", and frame marks a frame. `written` are the bounds holders of
 * every legible text, values included, and `legible` those of the legible names. */
export function seatMarks(shapes, written, legible) {
  // Graphics whose paint touches join into one mark.
  const parts = connected(shapes, touches).map((drawn) => {
    const frames = drawn.filter((v) => v.frame);
    return {
      box: span(drawn.map((v) => v.box)),
      drawn,
      empty: frames.length > 0 && !drawn.some((v) => frames.some((f) => inside(v, f))),
    };
  });
  // A mark holds content when it encloses another mark or any text, a name or a written value. An empty frame waits
  // for its content whatever name stands beside it; any other mark is named by a legible name within reach.
  const named = new Set();
  parts.forEach(({ box, empty }, i) => {
    const holds =
      parts.some((other, j) => j !== i && encloses(box, other.box)) ||
      written.some((v) => encloses(box, v.bounds));
    if (holds || (!empty && legible.some((v) => places(v.bounds, box)))) named.add(i);
  });
  // A mark drawn inside a named mark is part of what that name names.
  for (let grew = true; grew;) {
    grew = false;
    parts.forEach(({ box }, i) => {
      if (!named.has(i) && parts.some((other, j) => named.has(j) && encloses(other.box, box))) {
        named.add(i);
        grew = true;
      }
    });
  }
  // Repeated shapes: one kind and size that do not touch each other, from two to MOST_MEMBERS of them.
  const repeated = connected(
    shapes.filter((v) => Math.max(...size(v.box)) >= DETAIL),
    (a, b) => alike(a, b) && !touches(a, b),
  )
    .filter((group) => group.length >= 2 && group.length <= MOST_MEMBERS)
    .flatMap((group, set) => group.map((shape) => ({ shape, set })));
  // Repeated shapes that touch draw one member while together they stay the size of an icon, such as a figure's head
  // and shoulders, or when they paint one place, such as a disc's fill and outline; a member stands in a list while
  // another member repeats one of its shapes.
  // Each set's bounds are kept at its root, so whether two sets join is judged on all they already hold.
  const sets = disjointSets(repeated.length),
    bounds = repeated.map((v) => v.shape.box);
  for (let i = 0; i < repeated.length; i++)
    for (let j = i + 1; j < repeated.length; j++) {
      const a = sets.find(i),
        b = sets.find(j),
        joint = span([bounds[a], bounds[b]]);
      if (
        a !== b &&
        (Math.max(...size(joint)) <= ICON ||
          sameBox(repeated[i].shape.box, repeated[j].shape.box)) &&
        touches(repeated[i].shape, repeated[j].shape)
      ) {
        sets.join(i, j);
        bounds[b] = joint;
      }
    }
  const drawnOnce = sets.groups(repeated).map((group) => ({
    box: span(group.map((v) => v.shape.box)),
    shapes: group.map((v) => v.shape),
    sets: new Set(group.map((v) => v.set)),
  }));
  // A member drawn inside another member smaller than a frame is part of it, such as the figure on a station's disc;
  // members inside a frame are its content.
  const figures = drawnOnce.filter(
    (f) =>
      !drawnOnce.some(
        (g) =>
          g !== f &&
          encloses(g.box, f.box) &&
          !sameBox(g.box, f.box) &&
          size(g.box).some((d, k) => d < FRAME[k]),
      ),
  );
  const members = figures.filter((f) =>
    figures.some((g) => g !== f && [...f.sets].some((set) => g.sets.has(set))),
  );
  // A member holding a name is named; every other name names the nearest member it reaches, one member each.
  const taken = new Set(),
    memberNamed = new Set();
  members.forEach((m, j) => {
    const held = legible.findIndex((v, i) => !taken.has(i) && encloses(m.box, v.bounds));
    if (held >= 0) {
      taken.add(held);
      memberNamed.add(j);
    }
  });
  const pairs = [];
  legible.forEach((v, i) =>
    members.forEach((m, j) => {
      if (!taken.has(i) && !memberNamed.has(j) && places(v.bounds, m.box))
        pairs.push([gap(m.box, v.bounds), i, j]);
    }),
  );
  for (const [, i, j] of pairs.sort((a, b) => a[0] - b[0]))
    if (!taken.has(i) && !memberNamed.has(j)) {
      taken.add(i);
      memberNamed.add(j);
    }
  // A mark that is itself one member is judged as that member.
  const rows = [];
  parts.forEach(({ box, drawn }, i) => {
    if (!members.some((m) => sameBox(m.box, box) && m.shapes.every((v) => drawn.includes(v))))
      rows.push({ box, named: named.has(i), member: false });
  });
  return [
    ...rows,
    ...members.map((m, j) => ({ box: m.box, named: memberNamed.has(j), member: true })),
  ];
}
