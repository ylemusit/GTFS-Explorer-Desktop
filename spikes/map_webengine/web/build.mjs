import {copyFile} from "node:fs/promises";
import {build} from "esbuild";

await build({
  entryPoints: ["src/app.js"],
  bundle: true,
  format: "iife",
  outfile: "../assets/map_bundle.js"
});
await copyFile(
  "node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs",
  "../assets/map_worker.mjs"
);
await copyFile(
  "node_modules/maplibre-gl/dist/maplibre-gl-shared.mjs",
  "../assets/maplibre-gl-shared.mjs"
);
