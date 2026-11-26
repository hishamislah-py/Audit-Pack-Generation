import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The Ringfence server sends no CORS headers and its CSP is default-src 'self' (contract §1):
// proxy /api to it so the app and the API share one origin.
const api = { '/api': { target: process.env.RINGFENCE_API || 'http://127.0.0.1:8780', changeOrigin: false } };

// `vite build --mode backend` (npm run build:backend) produces the same-origin build that the Smart Parser
// server serves under /analyst/ (smartparser/webapp/server.py). No inline script: the server CSP is default-src 'self'.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === 'backend' ? '/analyst/' : '/',
  build: mode === 'backend'
    ? { outDir: '../smartparser/webapp/analyst', emptyOutDir: true, modulePreload: { polyfill: false } }
    : {},
  server: { port: 5173, proxy: api },
  preview: { port: 4173, proxy: api }
}));
