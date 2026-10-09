import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `npm run dev` forwards API and WebSocket calls to the backend, like nginx does in the
// Docker stack; `npm run dev:mock` forwards them to the Prism mock server (`npm run mock`).
// Point it elsewhere with VITE_API_PROXY_TARGET=http://host:port.
const MOCK_SERVER = 'http://127.0.0.1:4010'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const apiTarget =
    process.env.VITE_API_PROXY_TARGET ?? (mode === 'mock' ? MOCK_SERVER : 'http://localhost:8000')
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
        '/ws': { target: apiTarget, changeOrigin: true, ws: true },
      },
    },
  }
})
