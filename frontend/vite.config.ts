import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Локальная разработка: `npm run dev` на :5173, запросы /api уходят в стек docker compose (gateway :8090)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8090" },
  },
});
