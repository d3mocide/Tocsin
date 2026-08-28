import { defineConfig } from "vite";
import { mockApiPlugin } from "./mock-plugin.ts";


// API_BASE_URL is baked in at build time (Vite's import.meta.env.* convention) --
// see src/api.ts. Defaults to same-origin, unprefixed, since the production
// build is served directly by the api service (services/api/Dockerfile's
// `web` build stage); local `npm run dev` overrides via a .env.local with
// VITE_API_BASE_URL=http://localhost:8000.
// If VITE_API_BASE_URL is unset during `npm run dev`, mockApiPlugin supplies
// realistic mock data and live SSE event streams for UI development.
export default defineConfig({
  plugins: [mockApiPlugin()],
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

