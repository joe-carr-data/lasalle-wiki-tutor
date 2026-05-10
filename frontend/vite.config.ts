import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite serves the dev UI on :5173 and proxies /api/* + /health to the
// FastAPI backend on :8000. Production build emits to ./dist, which
// FastAPI mounts as static files via streaming.py.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api':    { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    emptyOutDir: true,
  },
});
