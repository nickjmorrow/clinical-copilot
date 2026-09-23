import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
// `vitest/config` rather than `vite`: same function, plus the `test` key
// below. Vitest reads this file, so the `src/` alias and the plugins are
// already whatever the app runs with — there is no second config to keep in
// step.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // Absolute imports from src/. Relative paths (`../../api/client`) stop
    // being readable about three directories in.
    alias: { src: '/src' },
  },
  server: {
    host: true,
    port: 3000,
    proxy: {
      // Everything under /api goes to the backend, so the browser only ever
      // talks to one origin. No CORS in dev, and no API URL baked into the
      // client bundle.
      '/api': {
        changeOrigin: true,
        target: process.env.BACKEND_ORIGIN ?? 'http://localhost:8000',
      },
    },
    watch: {
      // Docker on macOS does not deliver filesystem events across the bind
      // mount, so HMR silently stops working without polling. Costs a little
      // idle CPU; saves an hour of wondering why saves do nothing.
      usePolling: true,
    },
  },
  test: {
    // Node, not jsdom. Everything tested here is a pure function of data — the
    // fold in `turns.ts`, the split in `markdown.ts`, the formatters — and
    // there is deliberately no component rendering in the suite. Components in
    // this app are arrangement; the logic worth pinning was moved out of them
    // on purpose, and testing the arrangement instead would mean a DOM, a
    // renderer, and a set of tests that break when a class name changes.
    //
    // If you add a test that genuinely needs a DOM, add jsdom then. Not before.
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
