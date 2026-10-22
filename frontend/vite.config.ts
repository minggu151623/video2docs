import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode }) => {
  const appEnv = loadEnv(mode, "..", "APP_");
  return {
    plugins: [react()],
    server: {
      proxy: { "/api": `http://127.0.0.1:${appEnv.APP_PORT || "8000"}` },
    },
  };
});
