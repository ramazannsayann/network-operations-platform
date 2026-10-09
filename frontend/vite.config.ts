import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `npm run dev` forwards API and WebSocket calls to the backend, like nginx does in the
// Docker stack. Point it elsewhere with VITE_API_PROXY_TARGET=http://host:port.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/ws': { target: apiTarget, changeOrigin: true, ws: true },
    },
  },
})
