import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo el frontend corre en 5173 y se apoya en wally-web (8080) para
// vídeo, websockets y API. Compilado, FastAPI sirve todo desde ui/dist.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: "ws://localhost:8080", ws: true },
      "/api": "http://localhost:8080",
      "/stream.mjpeg": "http://localhost:8080",
      "/snapshot.jpg": "http://localhost:8080",
    },
  },
  build: {
    outDir: "dist",
    // Un robot se controla desde el móvil por wifi local: conviene poco peso
    // y nada de code-splitting innecesario.
    chunkSizeWarningLimit: 600,
  },
});
