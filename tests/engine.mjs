/** The installed filmkit release, as uv.lock pins it: the tests import its Node modules from where uv installed it. */
import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const PACKAGE = execFileSync(
  "uv",
  [
    "run",
    "--frozen",
    "--offline",
    "--no-sync",
    "python",
    "-c",
    "import filmkit, pathlib; print(pathlib.Path(filmkit.__file__).parent)",
  ],
  { encoding: "utf8" },
).trim();

/** The URL of one of the engine's modules, from its path below the package. */
export const engineModule = (path) => pathToFileURL(join(PACKAGE, path)).href;
