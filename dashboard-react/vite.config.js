import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // `npm run dev` serves the app but has no Python behind it, so /api would
    // 404 and the dashboard would silently fall back to the static export --
    // including the run form, which would claim it needs a backend that is in
    // fact running. Forwarding to src.server keeps both halves live while
    // working on the front end.
    proxy: {
      '/api': {
        target: process.env.MAVDITTO_API ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
