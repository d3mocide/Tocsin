import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import { mockApiPlugin } from "./mock-plugin.ts";

// maplibre-gl-worker.mjs (loaded via setWorkerUrl() in src/views/map.ts) has
// its own internal, unrewritten `import ... from "./maplibre-gl-shared.mjs"`.
// Vite's `?url` import of the worker copies it as an opaque asset without
// touching that internal import, so at runtime the worker still requests a
// literal, unhashed "maplibre-gl-shared.mjs" next to wherever it's served
// from. `vite build` has no other reason to know about that file, so without
// this it 404s (dev is unaffected -- Vite's dev server serves node_modules
// files directly, so the worker's relative import just resolves there).
function maplibreWorkerSharedChunk(): Plugin {
  return {
    name: "maplibre-worker-shared-chunk",
    apply: "build",
    generateBundle() {
      const src = fileURLToPath(
        new URL("node_modules/maplibre-gl/dist/maplibre-gl-shared.mjs", import.meta.url),
      );
      this.emitFile({ type: "asset", fileName: "assets/maplibre-gl-shared.mjs", source: readFileSync(src) });
    },
  };
}

// API_BASE_URL is baked in at build time (Vite's import.meta.env.* convention) --
// see src/api.ts. Defaults to same-origin, unprefixed, since the production
// build is served directly by the api service (services/api/Dockerfile's
// `web` build stage); local `npm run dev` overrides via a .env.local with
// VITE_API_BASE_URL=http://localhost:8000.
// If VITE_API_BASE_URL is unset during `npm run dev`, mockApiPlugin supplies
// realistic mock data and live SSE event streams for UI development.
export default defineConfig({
  plugins: [mockApiPlugin(), maplibreWorkerSharedChunk()],
  server: {
    port: 5173,
  },
  // maplibre-gl loads its worker via a same-directory `new URL(...)` relative
  // to its own module URL; Vite's dep pre-bundling copies the entry chunk but
  // not that sibling file, so pre-bundling must be skipped for it or the
  // worker 404s in dev (production builds are unaffected).
  optimizeDeps: {
    exclude: ["maplibre-gl"],
  },
});

