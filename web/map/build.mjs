import {copyFile, mkdir} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {build} from "esbuild";

const output = new URL("./dist/", import.meta.url);
await mkdir(output, {recursive: true});

await build({
  entryPoints: ["src/app.js"],
  bundle: true,
  format: "iife",
  legalComments: "none",
  outfile: fileURLToPath(new URL("map_bundle.js", output)),
});
await Promise.all([
  copyFile("node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs", new URL("map_worker.mjs", output)),
  copyFile("node_modules/maplibre-gl/dist/maplibre-gl-shared.mjs", new URL("maplibre-gl-shared.mjs", output)),
  copyFile("node_modules/maplibre-gl/dist/maplibre-gl.css", new URL("maplibre-gl.css", output)),
]);
