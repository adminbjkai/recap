import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/job": "http://127.0.0.1:8765"
    }
  }
});
