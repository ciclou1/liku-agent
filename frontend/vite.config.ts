import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    headers: { "Cache-Control": "no-store" },
    proxy: {
      "/api": {
        // 平衡利库后端；容器内经 VITE_PROXY_TARGET 指向宿主机
        target: process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8020",
        changeOrigin: true,
      },
    },
  },
});
