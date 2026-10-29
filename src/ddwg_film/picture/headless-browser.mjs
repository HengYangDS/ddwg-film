/** The headless browser the film's real-browser checks drive: the chrome-headless-shell HyperFrames caches, launched
 * through the puppeteer-core of the OpenMontage toolkit that renders the film. FILM_CHROMIUM_PATH names another
 * browser and FILM_OPENMONTAGE_ROOT another toolkit. */
import { readdir } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const TOOLKIT = ".local/share/openmontage/08e2151fa02de28a5d6a312b3d575692bf147ad7";
const BROWSERS = ".cache/hyperframes/chrome/chrome-headless-shell";

/** The browser to run: FILM_CHROMIUM_PATH, or the newest chrome-headless-shell HyperFrames has cached. */
export async function browserPath() {
  if (process.env.FILM_CHROMIUM_PATH) return process.env.FILM_CHROMIUM_PATH;
  const cache = join(homedir(), BROWSERS);
  const version = (await readdir(cache).catch(() => []))
    .filter((v) => v.startsWith("mac_arm-"))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
    .at(-1);
  if (!version) throw Error("No existing HyperFrames browser; set FILM_CHROMIUM_PATH");
  return join(cache, version, "chrome-headless-shell-mac-arm64/chrome-headless-shell");
}

/** Launch that browser headless; `options` are puppeteer's launch options, such as its arguments and viewport. */
export async function launchBrowser(options) {
  const toolkit = process.env.FILM_OPENMONTAGE_ROOT ?? join(homedir(), TOOLKIT);
  const { default: puppeteer } = await import(
    pathToFileURL(
      join(
        toolkit,
        ".runtime/hyperframes/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js",
      ),
    ).href
  );
  return puppeteer.launch({ executablePath: await browserPath(), headless: true, ...options });
}
