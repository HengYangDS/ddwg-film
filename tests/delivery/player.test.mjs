/** Exercise the pure parts of the delivered-player and cover checks: the delivery members, binding verification,
 * PNG decoding and the cover comparison. */
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { crc32, deflateSync } from "node:zlib";

import {
  bindingProblems,
  changedMembers,
  compareImages,
  decodePng,
  deliveryMembers,
  digestFile,
  seekPoints,
} from "../../src/filmkit/delivery/player-check.mjs";

const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const FILM = { slug: "ddwg", duration: 1500 };
const binding = (destination = "/delivery") => ({
  destination,
  film: FILM,
  members: deliveryMembers(FILM.slug).map((path) => ({ path, sha256: sha(path) })),
});

const chunk = (type, body) => {
  const head = Buffer.alloc(8),
    tail = Buffer.alloc(4);
  head.writeUInt32BE(body.length);
  head.write(type, 4, "latin1");
  tail.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), body])));
  return Buffer.concat([head, body, tail]);
};
const paeth = (a, b, c) => {
  const p = a + b - c,
    pa = Math.abs(p - a),
    pb = Math.abs(p - b),
    pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
};
/** Encode 8-bit RGB or RGBA pixels as a PNG, filtering row y with filter y % 5 so every filter type is exercised. */
function encodePng(width, height, channels, pixels, { depth = 8, interlace = 0 } = {}) {
  const stride = width * channels,
    rows = [];
  for (let y = 0; y < height; y++) {
    const filter = y % 5,
      line = pixels.subarray(y * stride, (y + 1) * stride);
    const above = y ? pixels.subarray((y - 1) * stride, y * stride) : new Uint8Array(stride),
      row = Buffer.alloc(stride + 1);
    row[0] = filter;
    for (let x = 0; x < stride; x++) {
      const a = x < channels ? 0 : line[x - channels],
        b = above[x],
        c = x < channels ? 0 : above[x - channels];
      row[x + 1] = line[x] - [0, a, b, (a + b) >> 1, paeth(a, b, c)][filter];
    }
    rows.push(row);
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width);
  header.writeUInt32BE(height, 4);
  header.set([depth, channels === 4 ? 6 : 2, 0, 0, interlace], 8);
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}
const pattern = (width, height, channels) =>
  Uint8Array.from({ length: width * height * channels }, (_, i) => (i * 37 + (i >> 3) * 91) & 255);
const opaque = (rgb) =>
  Uint8Array.from({ length: (rgb.length / 3) * 4 }, (_, i) =>
    i % 4 === 3 ? 255 : rgb[(i >> 2) * 3 + (i % 4)],
  );

test("the delivery has the entry page and ten members per language", () => {
  const edition = (code) =>
    [
      `ddwg-${code}-uhd.mp4`,
      `ddwg-${code}-1080p-captioned.mp4`,
      "ddwg-cover.png",
      "ddwg-cover.jpg",
      `ddwg-${code}.srt`,
      `ddwg-${code}.vtt`,
      `ddwg-${code}-transcript.md`,
      "chapters.json",
      "chapters.ffmeta",
      "index.html",
    ].map((name) => `${code}/${name}`);
  assert.deepEqual(deliveryMembers("ddwg"), ["index.html", ...edition("zh"), ...edition("en")]);
  assert.equal(new Set(deliveryMembers("ddwg")).size, 21);
});

test("a binding names an absolute destination, the film and exactly its delivery members", () => {
  assert.deepEqual(bindingProblems(binding()), []);
  assert.deepEqual(bindingProblems(binding("Documents/ddwg")), [
    "destination is not an absolute path",
  ]);
  const finderCopy = binding();
  finderCopy.members.push({ path: "zh/ddwg-zh 2.srt", sha256: sha("copy") });
  assert.deepEqual(bindingProblems(finderCopy), ["unexpected members: zh/ddwg-zh 2.srt"]);
  const short = binding();
  short.members = short.members.filter((member) => member.path !== "en/index.html");
  assert.deepEqual(bindingProblems(short), ["missing members: en/index.html"]);
  const twice = binding();
  twice.members.push(twice.members[0]);
  assert.deepEqual(bindingProblems(twice), ["duplicate members"]);
  const unhashed = binding();
  unhashed.members[3].sha256 = "abc";
  assert.deepEqual(bindingProblems(unhashed), [`${unhashed.members[3].path}: no SHA-256`]);
  assert.deepEqual(bindingProblems({ ...binding(), film: { slug: "DDWG", duration: 0 } }), [
    "film names no file prefix",
    "film names no duration",
  ]);
  const another = { ...binding(), film: { slug: "another", duration: 1500 } };
  assert.deepEqual(
    bindingProblems(another).map((problem) => problem.split(":")[0]),
    ["missing members", "unexpected members"],
  );
  assert.deepEqual(bindingProblems({}), [
    "destination is not an absolute path",
    "film names no file prefix",
    "film names no duration",
  ]);
});

test("a delivery readback binds only when it matched its sources with nothing beside them", () => {
  assert.deepEqual(bindingProblems({ ...binding(), all_match: true, unexpected: [] }), []);
  assert.deepEqual(bindingProblems({ ...binding(), all_match: false, unexpected: [] }), [
    "the readback does not match its sources",
  ]);
  assert.deepEqual(
    bindingProblems({ ...binding(), all_match: false, unexpected: ["zh/ddwg-zh 2.srt"] }),
    [
      "the readback does not match its sources",
      "unexpected entries at the destination: zh/ddwg-zh 2.srt",
    ],
  );
});

test("members whose destination bytes changed or vanished are found", async () => {
  const destination = await mkdtemp(join(tmpdir(), "delivery-"));
  try {
    await mkdir(join(destination, "zh"));
    const members = [];
    for (const path of ["index.html", "zh/index.html", "zh/chapters.json"]) {
      await writeFile(join(destination, path), `body of ${path}`);
      members.push({ path, sha256: sha(`body of ${path}`) });
    }
    assert.equal(await digestFile(join(destination, "index.html")), sha("body of index.html"));
    assert.deepEqual(await changedMembers({ destination, members }), []);
    await writeFile(join(destination, "zh/index.html"), "edited");
    await rm(join(destination, "zh/chapters.json"));
    assert.deepEqual(await changedMembers({ destination, members }), [
      "zh/index.html",
      "zh/chapters.json",
    ]);
  } finally {
    await rm(destination, { recursive: true, force: true });
  }
});

test("PNG decoding reverses every scanline filter for RGB and RGBA", () => {
  for (const channels of [3, 4]) {
    const pixels = pattern(7, 10, channels),
      decoded = decodePng(encodePng(7, 10, channels, pixels));
    assert.deepEqual([decoded.width, decoded.height], [7, 10]);
    assert.deepEqual(decoded.data, channels === 4 ? pixels : opaque(pixels));
  }
});

test("PNG decoding refuses what it does not decode", () => {
  assert.throws(() => decodePng(Buffer.from("not a png at all")), /Not a PNG/);
  assert.throws(() => decodePng(encodePng(2, 2, 3, pattern(2, 2, 3), { depth: 16 })), /Only 8-bit/);
  assert.throws(
    () => decodePng(encodePng(2, 2, 3, pattern(2, 2, 3), { interlace: 1 })),
    /Only 8-bit/,
  );
  const cut = encodePng(4, 4, 4, pattern(4, 4, 4));
  const header = cut.subarray(16, 24);
  header.writeUInt32BE(5, 4);
  assert.throws(() => decodePng(cut), /does not match its header/);
});

test("the tracked cover decodes at UHD on the film's ground", async () => {
  const cover = decodePng(
    await readFile(new URL("../../assets/cover/ddwg-cover.png", import.meta.url)),
  );
  assert.deepEqual([cover.width, cover.height], [3840, 2160]);
  for (const offset of [0, (1079 * 3840 + 1919) * 4, cover.data.length - 4])
    assert.deepEqual([...cover.data.subarray(offset, offset + 4)], [15, 21, 25, 255]);
});

test("cover comparison counts differing pixels and the largest channel difference", () => {
  const rgb = pattern(6, 5, 3),
    painted = decodePng(encodePng(6, 5, 4, opaque(rgb))),
    tracked = decodePng(encodePng(6, 5, 3, rgb));
  // The painted canvas is RGBA and the tracked cover RGB; opaque pixels with equal colour are identical.
  assert.deepEqual(compareImages(painted, tracked), {
    sizes: [
      [6, 5],
      [6, 5],
    ],
    differing_pixels: 0,
    max_difference: 0,
    identical: true,
  });
  const changed = { ...painted, data: Uint8Array.from(painted.data) };
  changed.data[0] = (changed.data[0] + 9) & 255;
  changed.data[4 * 7 + 3] = 200;
  assert.deepEqual(compareImages(changed, tracked), {
    sizes: [
      [6, 5],
      [6, 5],
    ],
    differing_pixels: 2,
    max_difference: 55,
    identical: false,
  });
  const wider = decodePng(encodePng(7, 5, 3, pattern(7, 5, 3)));
  assert.deepEqual(compareImages(wider, tracked), {
    sizes: [
      [7, 5],
      [6, 5],
    ],
    differing_pixels: null,
    max_difference: null,
    identical: false,
  });
});

test("seek points sit two seconds in, at the middle and four seconds before the end", () => {
  assert.deepEqual(seekPoints(1500), [2, 750, 1496]);
});

test("the player check refuses a malformed invocation before opening a browser", () => {
  const tool = fileURLToPath(
    new URL("../../src/filmkit/delivery/player-check.mjs", import.meta.url),
  );
  for (const args of [
    [],
    ["players", "binding.json"],
    ["cover", "stage", "cover.png"],
    ["--x"],
    ["play"],
  ]) {
    const result = spawnSync(process.execPath, [tool, ...args], { encoding: "utf8" });
    assert.equal(result.status, 2, args.join(" "));
    assert.equal(result.stdout, "", args.join(" "));
    assert.ok(
      result.stderr.includes("Usage: node src/filmkit/delivery/player-check.mjs"),
      args.join(" "),
    );
  }
});
