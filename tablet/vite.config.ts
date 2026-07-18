import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  // Served from https://bmasscha.github.io/fable-volleyscouting/ (GitHub Pages
  // project site). Override with --base=/ for root-hosted deploys.
  base: "/fable-volleyscouting/",
  esbuild: { jsx: "automatic", jsxImportSource: "preact" },
  plugins: [
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "icons/apple-touch-icon-180.png"],
      manifest: {
        name: "Fable Scouter",
        short_name: "Scouter",
        description: "Touch volleyball match scouting",
        start_url: ".",
        display: "standalone",
        orientation: "any",
        background_color: "#16212b",
        theme_color: "#16212b",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "icons/maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // Precache the whole build: the app is fully client-side (matches
        // live in browser storage), so this makes it work offline in the hall.
        globPatterns: ["**/*.{js,css,html,svg,png,ico,woff2}"],
        navigateFallback: "index.html",
      },
    }),
  ],
});
