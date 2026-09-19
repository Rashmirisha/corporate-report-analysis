import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy /api/* to the FastAPI backend during dev so the dashboard
    // can be wired to the live backend in a later stage without CORS
    // gymnastics. Stage 4A uses the dashboard shell only and does not
    // make any backend calls yet.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:3101',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
