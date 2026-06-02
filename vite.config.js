import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [tailwindcss()],
  build: {
    manifest: false,
    outDir: "static/dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: "assets/src/app.js",
        excel: "assets/src/excel.js",
      },
      output: {
        entryFileNames: "[name].js",
        assetFileNames: "[name].[ext]",
      },
    },
  },
});
