/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Bearer token sent with API calls; only set in mock mode (vite.config.ts). */
  readonly VITE_API_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
