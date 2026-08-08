import { defineConfig } from "vite";

// API_BASE_URL is baked in at build time (Vite's import.meta.env.* convention) --
// see src/api.ts. Defaults to same-origin /api, which the production Dockerfile's
// nginx config proxies to the api service; local `npm run dev` overrides via
// a .env.local with VITE_API_BASE_URL=http://localhost:8000.
export default defineConfig({
  server: {
    port: 5173,
  },
});
