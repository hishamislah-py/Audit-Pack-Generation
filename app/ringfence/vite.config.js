// Ringfence analyst application: React 18 + Vite.
//  npm run dev   -> http://127.0.0.1:5173/rf/  (proxies /api to the Python backend, default http://127.0.0.1:8780)
//  npm run build -> ../smartparser/webapp/ringfence/ (served same-origin by the backend at /rf/, CSP unchanged)
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = process.env.RINGFENCE_BACKEND || "http://127.0.0.1:8780";

export default defineConfig({
  base: "/rf/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: backend, changeOrigin: false } },
  },
  build: {
    outDir: "../smartparser/webapp/ringfence",
    emptyOutDir: true,
    sourcemap: false,
    modulePreload: { polyfill: false },   // no inline script: the backend CSP is script-src 'self'
    assetsInlineLimit: 0,                 // fonts as files, never data: URIs
  },
});
