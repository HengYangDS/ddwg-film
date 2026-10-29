/** The headless browser the film's real-browser checks drive: the chrome-headless-shell that the supply task installs
 * below build/runtime/tool-cache, launched through the repository's locked puppeteer-core. FILM_CHROMIUM_PATH names
 * another browser. */
import { readdir } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer-core";

/* The supplied browser builds, below the repository root three levels above this module. */
const BROWSERS = fileURLToPath(
  new URL("../../../build/runtime/tool-cache/browsers/chrome-headless-shell", import.meta.url),
);

/** The newest macOS arm64 chrome-headless-shell in a folder of builds, or none. */
export async function newestBrowser(folder) {
  const version = (await readdir(folder).catch(() => []))
    .filter((v) => v.startsWith("mac_arm-"))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
    .at(-1);
  return version && join(folder, version, "chrome-headless-shell-mac-arm64/chrome-headless-shell");
}

/** The browser to run: FILM_CHROMIUM_PATH, or the newest supplied chrome-headless-shell. */
export async function browserPath() {
  if (process.env.FILM_CHROMIUM_PATH) return process.env.FILM_CHROMIUM_PATH;
  const supplied = await newestBrowser(BROWSERS);
  if (!supplied) throw Error("No supplied browser; run the supply task or set FILM_CHROMIUM_PATH");
  return supplied;
}

/** Launch that browser headless through `driver`; `options` are puppeteer's launch options, such as its arguments
 * and viewport. */
export async function launchBrowser(options, driver = puppeteer) {
  return driver.launch({ executablePath: await browserPath(), headless: true, ...options });
}
