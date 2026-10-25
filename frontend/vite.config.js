import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api goes to the nginx proxy (which does the auth), not straight to the API.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": process.env.VITE_DEV_PROXY || "http://localhost:3040" },
  },
});
