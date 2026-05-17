/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: false,
      },
      "/healthz": "http://localhost:8000",
      "/readyz": "http://localhost:8000",
      "/qr": "http://localhost:8000",
      "/pay": "http://localhost:8000",
      "/admin": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    target: "es2022",
    chunkSizeWarningLimit: 600,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
