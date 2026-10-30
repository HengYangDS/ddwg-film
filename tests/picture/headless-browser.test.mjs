/** Exercise how the real-browser checks find and launch their headless browser, without starting one. */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  browserPath,
  launchBrowser,
  newestBrowser,
} from "../../src/filmkit/picture/headless-browser.mjs";

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

test("otherwise the newest supplied macOS arm64 build runs", async () => {
  const folder = await mkdtemp(join(tmpdir(), "film-browsers-"));
  try {
    // Without a build, or with no build for this platform, there is nothing to run.
    assert.equal(await newestBrowser(join(folder, "absent")), undefined);
    await mkdir(join(folder, "linux-152.0.1"));
    assert.equal(await newestBrowser(folder), undefined);
    // Versions compare by number, so 152 is newer than 99.
    for (const version of ["mac_arm-99.0.4844.51", "mac_arm-152.0.7977.30", "mac_arm-152.0.799.1"])
      await mkdir(join(folder, version));
    assert.equal(
      await newestBrowser(folder),
      join(
        folder,
        "mac_arm-152.0.7977.30",
        "chrome-headless-shell-mac-arm64/chrome-headless-shell",
      ),
    );
  } finally {
    await rm(folder, { recursive: true, force: true });
  }
});

test("the browser launches headless through the driver, with the caller's options", async () => {
  // A stand-in driver that returns the options it was asked to launch with.
  const driver = { launch: async (options) => ({ launched: options }) };
  const options = { args: ["--allow-file-access-from-files"], defaultViewport: { width: 1920 } };
  await withEnvironment({ FILM_CHROMIUM_PATH: "/opt/chromium/chrome" }, async () =>
    assert.deepEqual(await launchBrowser(options, driver), {
      launched: { executablePath: "/opt/chromium/chrome", headless: true, ...options },
    }),
  );
});
