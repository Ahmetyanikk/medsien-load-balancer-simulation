import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// server.proxy only applies to `vite dev` — it has no effect on `vite build`
// output or `vite preview`, so this is development-only by construction.
// The production nginx reverse proxy (Day 2B-2) replaces this role at runtime.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    css: true,
  },
});
