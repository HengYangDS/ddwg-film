/** Exercise how the real-browser checks find and launch their headless browser, without starting one. */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { browserPath, launchBrowser } from "../../src/filmkit/picture/headless-browser.mjs";

/* Run with these environment variables set (undefined removes one), restoring the previous values after. */
async function withEnvironment(values, run) {
  const saved = Object.fromEntries(Object.keys(values).map((key) => [key, process.env[key]]));
  const assign = (entries) => {
    for (const [key, value] of Object.entries(entries))
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
  };
  assign(values);
  try {
    return await run();
  } finally {
    assign(saved);
  }
}

test("FILM_CHROMIUM_PATH names the browser to run", async () => {
  await withEnvironment({ FILM_CHROMIUM_PATH: "/opt/chromium/chrome" }, async () =>
    assert.equal(await browserPath(), "/opt/chromium/chrome"),
  );
});

test("otherwise the newest chrome-headless-shell HyperFrames has cached runs", async () => {
  const home = await mkdtemp(join(tmpdir(), "ddwg-home-"));
  try {
    const cache = join(home, ".cache/hyperframes/chrome/chrome-headless-shell");
    await withEnvironment({ FILM_CHROMIUM_PATH: undefined, HOME: home }, async () => {
      // Without a cache, or with no browser for this platform in it, there is nothing to run.
      await assert.rejects(
        browserPath(),
        /No existing HyperFrames browser; set FILM_CHROMIUM_PATH/,
      );
      await mkdir(join(cache, "linux-152.0.1"), { recursive: true });
      await assert.rejects(browserPath(), /No existing HyperFrames browser/);
      // Versions compare by number, so 152 is newer than 99.
      for (const version of [
        "mac_arm-99.0.4844.51",
        "mac_arm-152.0.7977.30",
        "mac_arm-152.0.799.1",
      ])
        await mkdir(join(cache, version));
      assert.equal(
        await browserPath(),
        join(
          cache,
          "mac_arm-152.0.7977.30",
          "chrome-headless-shell-mac-arm64/chrome-headless-shell",
        ),
      );
    });
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});

test("the browser launches headless through the toolkit's puppeteer, with the caller's options", async () => {
  const toolkit = await mkdtemp(join(tmpdir(), "ddwg-toolkit-"));
  try {
    // A stand-in puppeteer that returns the options it was asked to launch with.
    const module = join(toolkit, ".runtime/hyperframes/node_modules/puppeteer-core");
    await mkdir(join(module, "lib/puppeteer"), { recursive: true });
    await writeFile(join(module, "package.json"), JSON.stringify({ type: "module" }));
    await writeFile(
      join(module, "lib/puppeteer/puppeteer-core.js"),
      "export default { launch: async (options) => ({ launched: options }) };\n",
    );
    const options = { args: ["--allow-file-access-from-files"], defaultViewport: { width: 1920 } };
    await withEnvironment(
      { FILM_OPENMONTAGE_ROOT: toolkit, FILM_CHROMIUM_PATH: "/opt/chromium/chrome" },
      async () =>
        assert.deepEqual(await launchBrowser(options), {
          launched: { executablePath: "/opt/chromium/chrome", headless: true, ...options },
        }),
    );
  } finally {
    await rm(toolkit, { recursive: true, force: true });
  }
});
