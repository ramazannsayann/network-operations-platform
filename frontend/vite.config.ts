import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

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
    // Prism enforces the contract's bearer security; the real API does not check tokens
    // until M7. Mock mode therefore sends a placeholder token (src/api/client.ts).
    define:
      mode === 'mock'
        ? { 'import.meta.env.VITE_API_TOKEN': JSON.stringify('mock-not-checked') }
        : {},
    build: {
      rolldownOptions: {
        output: {
          // Libraries in chunks of their own, cached across deploys of the app code.
          codeSplitting: {
            groups: [
              { name: 'mantine', test: /node_modules[\\/]@mantine[\\/]/ },
              { name: 'icons', test: /node_modules[\\/]@tabler[\\/]/ },
              { name: 'cytoscape', test: /node_modules[\\/]cytoscape[\\/]/ },
              { name: 'vendor', test: /node_modules[\\/]/ },
            ],
          },
        },
      },
    },
    server: {
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
        '/ws': { target: apiTarget, changeOrigin: true, ws: true },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      css: false,
    },
  }
})
