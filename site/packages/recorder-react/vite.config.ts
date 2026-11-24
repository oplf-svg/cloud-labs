import { defineConfig } from "vite";

export default defineConfig({
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "dist",
    modulePreload: false,
    rollupOptions: { input: "src/main.tsx", output: { entryFileNames: "main.js", chunkFileNames: "[name].js" } },
  },
});
