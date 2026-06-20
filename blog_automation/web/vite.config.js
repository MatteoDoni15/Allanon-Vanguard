import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The app is served on :8080 (so blogs live at localhost:8080/blog_1, ...).
// All /api calls are proxied to the FastAPI backend on :8000, which keeps the
// browser on a single origin and avoids CORS during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 8080,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
