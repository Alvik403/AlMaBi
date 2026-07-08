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
        charts_page: "assets/src/charts_page.js",
        report_page: "assets/src/report_page.js",
        test_excel_panel: "assets/src/test_excel_panel.js",
      },
      output: {
        entryFileNames: "[name].js",
        assetFileNames: "[name].[ext]",
      },
    },
  },
});
