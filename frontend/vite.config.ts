import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api is proxied to FastAPI so the browser sees one origin (nginx does the same in compose)
const api = process.env.API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": api } },
  preview: { port: 4173, proxy: { "/api": api } },
});
