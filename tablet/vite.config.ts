import { defineConfig } from "vite";

// PWA plugin (service worker + manifest) is added in the packaging phase;
// keep the config minimal while the core translation is being verified.
export default defineConfig({
  esbuild: { jsx: "automatic", jsxImportSource: "preact" },
});
