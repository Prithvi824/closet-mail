/// <reference types="vitest/config" />
import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const API_TARGET = "http://localhost:8000";

// Dev server proxies every backend path so cookies stay same-origin, as behind Caddy in prod.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  build: {
    // The shell (React, router, query, Radix) is ~160 kB gzipped; pages are lazy chunks.
    chunkSizeWarningLimit: 600,
  },
  server: {
    proxy: {
      "/api": API_TARGET,
      "/hooks": API_TARGET,
      "/a/": API_TARGET,
      "/healthz": API_TARGET,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
