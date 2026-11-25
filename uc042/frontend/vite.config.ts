/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The dev server binds to 127.0.0.1:5173, an origin the FastAPI backend allows (UC042_CORS_ORIGINS default).
// The captured mock fixtures (dev-fixtures/) are served ONLY by the dev server when VITE_DATA_SOURCE=mock; production
// builds have no public directory, so no mock data is ever shipped.
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const mockDev = command === "serve" && env.VITE_DATA_SOURCE === "mock";
  return {
    plugins: [react()],
    publicDir: mockDev ? "dev-fixtures" : false,
    server: { host: "127.0.0.1", port: 5173, strictPort: true },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      css: false,
      testTimeout: 20000,
    },
  };
});
