import { build } from "esbuild";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputRoot = resolve(root, "../src/local_shell_mcp/ui/static");
const check = process.argv.includes("--check");
const temporary = check ? resolve(root, ".build-check") : outputRoot;
if (check) await rm(temporary, { recursive: true, force: true });
await mkdir(temporary, { recursive: true });

await build({
  entryPoints: [resolve(root, "src/index.js")],
  outfile: resolve(temporary, "xterm_bundle.js"),
  bundle: true,
  minify: true,
  legalComments: "none",
  platform: "browser",
  target: ["es2022"],
  format: "iife",
});
await cp(
  resolve(root, "node_modules/@xterm/xterm/css/xterm.css"),
  resolve(temporary, "xterm.css"),
);

const licenses = [];
for (const [name, path] of [
  ["@xterm/xterm 5.5.0", "node_modules/@xterm/xterm/LICENSE"],
  ["@xterm/addon-fit 0.10.0", "node_modules/@xterm/addon-fit/LICENSE"],
  ["@xterm/addon-image 0.8.0", "node_modules/@xterm/addon-image/LICENSE"],
]) {
  const license = (await readFile(resolve(root, path), "utf8")).trimEnd();
  licenses.push(`${name}\n${"=".repeat(name.length)}\n${license}`);
}
await writeFile(
  resolve(temporary, "xterm.LICENSE.txt"),
  `${licenses.join("\n\n")}\n`,
  "utf8",
);

if (check) {
  try {
    for (const name of ["xterm_bundle.js", "xterm.css", "xterm.LICENSE.txt"]) {
      const expected = await readFile(resolve(outputRoot, name));
      const actual = await readFile(resolve(temporary, name));
      if (!expected.equals(actual)) {
        throw new Error(`${name} is stale; run npm run build in ui-terminal`);
      }
    }
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}
