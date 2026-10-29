/** Read the delivered players back in a real browser, and paint the cover from a staged document.
 *
 * players: a binding names the destination and the SHA-256 of each of the 21 delivery members (the delivery
 * readback, or a review round's artifacts binding). The member bytes are checked before and after the browser read.
 * The read opens the language entry page and each language's player: page language, the delivered chapters, the
 * captioned viewing edition playing by default without a text track (captions are drawn in the picture), both
 * editions' duration and dimensions with decoding at three seek points, a chapter jump and the rendered transcript.
 * Requests outside the destination are refused and recorded; screenshots are written beside the receipt.
 * cover: paints window.renderCover() from a staged UHD document and compares its pixels with the tracked cover.
 * No human hearing or complete-film playback is claimed.
 * Usage: node src/filmkit/delivery/player-check.mjs players <binding.json> <receipt.json>
 *        node src/filmkit/delivery/player-check.mjs cover <stage-dir> <cover.png> <output.png> */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { inflateSync } from "node:zlib";

import { launchBrowser } from "../picture/headless-browser.mjs";

const USAGE =
  "Usage: node src/filmkit/delivery/player-check.mjs players <binding.json> <receipt.json>\n" +
  "       node src/filmkit/delivery/player-check.mjs cover <stage-dir> <cover.png> <output.png>";
const LANGUAGES = { zh: "zh-CN", en: "en" };
/* Repository files resolve from the repository root, three levels above this module. */
const REPOSITORY = new URL("../../../", import.meta.url);
/** Each language's film script, whose duration both of its delivered editions must play. */
export const SCRIPTS = Object.freeze({
  zh: new URL("content/film-script.json", REPOSITORY),
  en: new URL("content/en/film-script.json", REPOSITORY),
});
const EDITIONS = [
  ["-uhd.mp4", [3840, 2160]],
  ["-1080p-captioned.mp4", [1920, 1080]],
];
const DEADLINE = 240000;

const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");

/** A file's SHA-256, streamed so that a film need not fit in memory. */
export async function digestFile(path) {
  const hash = createHash("sha256");
  for await (const block of createReadStream(path)) hash.update(block);
  return hash.digest("hex");
}

/** The 21 delivery members: the language entry page, then per language both movies, the cover as PNG and JPEG, SRT
 * and VTT subtitles, the transcript, chapters as JSON and FFmetadata, and the player. */
export function deliveryMembers() {
  return [
    "index.html",
    ...Object.keys(LANGUAGES).flatMap((code) =>
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
      ].map((name) => `${code}/${name}`),
    ),
  ];
}

/** Why a binding does not name one delivery; none for a binding with an absolute destination and exactly the delivery
 * members, each once with a SHA-256. A delivery readback must also have matched its sources with nothing beside them. */
export function bindingProblems(binding) {
  const problems = [];
  if (typeof binding?.destination !== "string" || !isAbsolute(binding.destination))
    problems.push("destination is not an absolute path");
  if (binding?.all_match === false) problems.push("the readback does not match its sources");
  if (binding?.unexpected?.length)
    problems.push(`unexpected entries at the destination: ${binding.unexpected.join(", ")}`);
  const members = Array.isArray(binding?.members) ? binding.members : [];
  const paths = members.map((member) => member?.path),
    expected = deliveryMembers();
  const missing = expected.filter((path) => !paths.includes(path)),
    extra = paths.filter((path) => !expected.includes(path));
  if (missing.length) problems.push(`missing members: ${missing.join(", ")}`);
  if (extra.length) problems.push(`unexpected members: ${extra.join(", ")}`);
  if (new Set(paths).size !== paths.length) problems.push("duplicate members");
  for (const member of members)
    if (!/^[0-9a-f]{64}$/.test(member?.sha256 ?? "")) problems.push(`${member?.path}: no SHA-256`);
  return problems;
}

/** The bound members whose bytes at the destination differ from the binding or are absent. */
export async function changedMembers(binding) {
  const changed = [];
  for (const member of binding.members) {
    const value = await digestFile(join(binding.destination, member.path)).catch(() => null);
    if (value !== member.sha256) changed.push(member.path);
  }
  return changed;
}

/** Two seconds in, the middle, and four seconds before the end. */
export const seekPoints = (duration) => [2, duration / 2, duration - 4];

const paeth = (a, b, c) => {
  const p = a + b - c,
    pa = Math.abs(p - a),
    pb = Math.abs(p - b),
    pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
};

/** Decode a PNG buffer, 8-bit and non-interlaced RGB or RGBA, into RGBA pixels; RGB pixels are opaque. */
export function decodePng(bytes) {
  if (!bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])))
    throw Error("Not a PNG");
  let width = 0,
    height = 0,
    channels = 0;
  const data = [];
  for (let at = 8; at + 8 <= bytes.length;) {
    const length = bytes.readUInt32BE(at),
      type = bytes.toString("latin1", at + 4, at + 8),
      body = bytes.subarray(at + 8, at + 8 + length);
    if (type === "IHDR") {
      [width, height] = [body.readUInt32BE(0), body.readUInt32BE(4)];
      channels = { 2: 3, 6: 4 }[body[9]] ?? 0;
      if (body[8] !== 8 || !channels || body[12] !== 0)
        throw Error("Only 8-bit non-interlaced RGB or RGBA PNG is decoded");
    } else if (type === "IDAT") data.push(body);
    else if (type === "IEND") break;
    at += 12 + length;
  }
  const raw = inflateSync(Buffer.concat(data)),
    stride = width * channels;
  if (!channels || raw.length !== (stride + 1) * height)
    throw Error("PNG pixel data does not match its header");
  const pixels = new Uint8Array(width * height * 4);
  let line = new Uint8Array(stride),
    above = new Uint8Array(stride);
  for (let y = 0; y < height; y++) {
    const start = y * (stride + 1),
      filter = raw[start];
    if (filter > 4) throw Error(`Unknown PNG filter ${filter}`);
    for (let x = 0; x < stride; x++) {
      const a = x < channels ? 0 : line[x - channels],
        b = above[x],
        c = x < channels ? 0 : above[x - channels];
      const predicted =
        filter === 0
          ? 0
          : filter === 1
            ? a
            : filter === 2
              ? b
              : filter === 3
                ? (a + b) >> 1
                : paeth(a, b, c);
      line[x] = (raw[start + 1 + x] + predicted) & 255;
    }
    for (let x = 0, i = 0, o = y * width * 4; x < width; x++, i += channels, o += 4) {
      pixels[o] = line[i];
      pixels[o + 1] = line[i + 1];
      pixels[o + 2] = line[i + 2];
      pixels[o + 3] = channels === 4 ? line[i + 3] : 255;
    }
    [line, above] = [above, line];
  }
  return { width, height, data: pixels };
}

/** Compare two decoded images: how many pixels differ and the largest channel difference. Images of different
 * sizes are not compared. */
export function compareImages(a, b) {
  const sizes = [
    [a.width, a.height],
    [b.width, b.height],
  ];
  if (a.width !== b.width || a.height !== b.height)
    return { sizes, differing_pixels: null, max_difference: null, identical: false };
  let differing = 0,
    largest = 0;
  for (let i = 0; i < a.data.length; i += 4) {
    let difference = 0;
    for (let k = i; k < i + 4; k++)
      difference = Math.max(difference, Math.abs(a.data[k] - b.data[k]));
    if (difference) {
      differing++;
      largest = Math.max(largest, difference);
    }
  }
  return {
    sizes,
    differing_pixels: differing,
    max_difference: largest,
    identical: differing === 0,
  };
}

async function readPlayers(browser, binding, receiptPath, report) {
  const root = binding.destination;
  assert.deepEqual(
    await changedMembers(binding),
    [],
    "Delivered members differ from their binding",
  );
  const page = await browser.newPage();
  page.setDefaultTimeout(30000);
  page.on("pageerror", (error) => report.console_errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") report.console_errors.push(message.text());
    if (message.type() === "warn") report.console_warnings.push(message.text());
  });
  page.on("requestfailed", (request) => {
    const error = request.failure()?.errorText;
    if (error !== "net::ERR_ABORTED") report.request_failures.push({ url: request.url(), error });
  });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    if (
      request.url().startsWith(pathToFileURL(root + "/").href) ||
      request.url().startsWith("data:")
    )
      request.continue();
    else {
      report.external_requests.push(request.url());
      request.abort();
    }
  });
  await page.goto(pathToFileURL(join(root, "index.html")).href, { waitUntil: "networkidle0" });
  report.language_links = await page.$$eval("nav a", (links) =>
    links.map((a) => a.getAttribute("href")),
  );
  assert.deepEqual(
    report.language_links,
    Object.keys(LANGUAGES).map((code) => `${code}/index.html`),
  );
  for (const [language, lang] of Object.entries(LANGUAGES)) {
    const { duration } = JSON.parse(await readFile(SCRIPTS[language], "utf8"));
    const { chapters } = JSON.parse(await readFile(join(root, language, "chapters.json"), "utf8"));
    await page.goto(pathToFileURL(join(root, language, "index.html")).href, {
      waitUntil: "networkidle0",
    });
    await page.waitForFunction(() => document.querySelector("video").readyState >= 1);
    const item = {
      language,
      editions: [],
      chapters: await page.$$eval("#chapters button", (buttons) =>
        buttons.map((b) => b.textContent),
      ),
    };
    assert.equal(await page.$eval("html", (e) => e.lang), lang);
    assert.deepEqual(
      item.chapters,
      chapters.map((chapter) => chapter.title),
    );
    // The viewing edition plays by default, and burned-in captions are not doubled by a text track.
    item.default_source = await page.$eval("video", (video) => video.currentSrc.split("/").pop());
    item.text_tracks = await page.$eval("video", (video) => video.textTracks.length);
    assert.equal(item.default_source, `ddwg-${language}-1080p-captioned.mp4`);
    assert.equal(item.text_tracks, 0);
    for (const [file, dimensions] of EDITIONS) {
      await page.click(`[data-file$="${file}"]`);
      await page.waitForFunction(
        (suffix) =>
          document.querySelector("video").currentSrc.endsWith(suffix) &&
          document.querySelector("video").readyState >= 1,
        {},
        file,
      );
      const state = await page.$eval("video", (video) => ({
        duration: video.duration,
        width: video.videoWidth,
        height: video.videoHeight,
        src: video.currentSrc,
        error: video.error?.code ?? null,
      }));
      assert.equal(state.duration, duration);
      assert.deepEqual([state.width, state.height], dimensions);
      assert.equal(state.error, null);
      state.seek_checks = [];
      for (const time of seekPoints(duration)) {
        await page.$eval(
          "video",
          (video, target) => {
            video.pause();
            video.muted = true;
            video.currentTime = target;
          },
          time,
        );
        await page.waitForFunction(
          (target) => {
            const v = document.querySelector("video");
            return !v.seeking && v.readyState >= 2 && Math.abs(v.currentTime - target) < 0.2;
          },
          {},
          time,
        );
        await page.$eval("video", (video) => video.play());
        await page.waitForFunction(
          (target) => document.querySelector("video").currentTime > target + 0.35,
          {},
          time,
        );
        const decoded = await page.$eval("video", (video) => {
          video.pause();
          const q = video.getVideoPlaybackQuality();
          return {
            time: video.currentTime,
            ready_state: video.readyState,
            error: video.error?.code ?? null,
            decoded_frames: q.totalVideoFrames,
            dropped_frames: q.droppedVideoFrames,
          };
        });
        assert.equal(decoded.error, null);
        assert.ok(decoded.decoded_frames > 0);
        state.seek_checks.push(decoded);
      }
      item.editions.push(state);
    }
    await page.click("#chapters button:nth-child(2)");
    await page.waitForFunction(() => !document.querySelector("video").paused);
    item.chapter_jump = await page.$eval("video", (video) => {
      video.pause();
      return video.currentTime;
    });
    assert.ok(item.chapter_jump >= chapters[1].start && item.chapter_jump < duration);
    const screenshot = join(dirname(receiptPath), `player-${language}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    report.screenshots.push({ path: screenshot, sha256: await digestFile(screenshot) });
    // The rendered transcript holds every chapter, and the footer link opens it.
    item.transcript_chapters = await page.$$eval("#transcript h2", (headings) => headings.length);
    assert.equal(item.transcript_chapters, chapters.length);
    await page.click('footer a[href="#transcript"]');
    item.transcript_open = await page.$eval("#transcript details", (details) => details.open);
    assert.equal(item.transcript_open, true);
    report.languages.push(item);
  }
  assert.deepEqual(report.external_requests, []);
  assert.deepEqual(report.request_failures, []);
  assert.deepEqual(report.console_errors, []);
  assert.deepEqual(await changedMembers(binding), [], "Delivered members changed during the read");
  report.members_unchanged = binding.members.length;
  await page.close();
}

/** Read the bound delivery's players back within an owned browser deadline and write the receipt. */
export async function checkPlayers(bindingPath, receiptPath) {
  const binding = JSON.parse(await readFile(bindingPath, "utf8"));
  const report = {
    started_at: new Date().toISOString(),
    destination: binding.destination,
    binding_sha256: await digestFile(bindingPath),
    scope:
      "Real-browser metadata, decode at seek points, chapter navigation and edition selection; no human hearing or complete-film playback",
    languages: [],
    console_errors: [],
    console_warnings: [],
    request_failures: [],
    external_requests: [],
    screenshots: [],
  };
  let browser, deadline;
  try {
    const problems = bindingProblems(binding);
    if (problems.length) throw Error(`Not a delivery binding: ${problems.join("; ")}`);
    browser = await launchBrowser({
      args: ["--autoplay-policy=no-user-gesture-required"],
      defaultViewport: { width: 1600, height: 1000, deviceScaleFactor: 1 },
    });
    report.browser_version = await browser.version();
    const reading = readPlayers(browser, binding, receiptPath, report);
    // A read still running at the deadline fails once its browser closes; that late failure is already reported.
    reading.catch(() => {});
    await Promise.race([
      reading,
      new Promise((_, reject) => {
        deadline = setTimeout(() => reject(Error("Owned browser deadline exceeded")), DEADLINE);
      }),
    ]);
    report.pass = true;
  } catch (error) {
    report.pass = false;
    report.error = String(error.stack ?? error);
  } finally {
    clearTimeout(deadline);
    if (browser) await browser.close();
    report.browser_closed = true;
    report.finished_at = new Date().toISOString();
    await writeFile(receiptPath, JSON.stringify(report, null, 2) + "\n");
  }
  return report;
}

/** Paint the cover from a staged UHD document, write it, and compare its pixels with the tracked cover. */
export async function paintCover(stage, cover, output) {
  const browser = await launchBrowser({
    args: ["--allow-file-access-from-files"],
    defaultViewport: { width: 3840, height: 2160, deviceScaleFactor: 1 },
  });
  try {
    const page = await browser.newPage();
    await page.goto(pathToFileURL(resolve(stage, "index.html")).href, {
      waitUntil: "load",
      timeout: 60000,
    });
    await page.evaluate(() => window.__filmReady);
    await page.evaluate(() => document.fonts.ready);
    const data = await page.evaluate(() => {
      window.renderCover();
      return document.getElementById("picture").toDataURL("image/png");
    });
    const painted = Buffer.from(data.split(",")[1], "base64"),
      tracked = await readFile(cover);
    await writeFile(output, painted);
    return {
      output,
      sha256: digest(painted),
      cover,
      cover_sha256: digest(tracked),
      ...compareImages(decodePng(painted), decodePng(tracked)),
    };
  } finally {
    await browser.close();
  }
}

if (import.meta.main) {
  let positionals = [];
  try {
    ({ positionals } = parseArgs({ allowPositionals: true }));
  } catch (error) {
    console.error(error.message);
  }
  const [command, ...args] = positionals;
  if (command === "players" && args.length === 2) {
    const report = await checkPlayers(args[0], args[1]);
    console.log(
      JSON.stringify({
        pass: report.pass,
        error: report.error,
        languages: report.languages.length,
      }),
    );
    process.exitCode = report.pass ? 0 : 1;
  } else if (command === "cover" && args.length === 3) {
    const result = await paintCover(args[0], args[1], args[2]);
    console.log(JSON.stringify(result));
    process.exitCode = result.identical ? 0 : 1;
  } else {
    console.error(USAGE);
    process.exitCode = 2;
  }
}
