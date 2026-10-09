import createClient from 'openapi-fetch'

import type { components, paths } from './schema'

/** Typed client for the NetOps API; paths, parameters and bodies come from the contract. */
export const api = createClient<paths>({ baseUrl: '/' })

// The API does not check tokens until M7. The Prism mock (npm run dev:mock) does enforce the
// declared bearer security, so mock mode sends a placeholder token (see vite.config.ts).
const token = import.meta.env.VITE_API_TOKEN
if (token) {
  api.use({
    onRequest({ request }) {
      request.headers.set('Authorization', `Bearer ${token}`)
      return request
    },
  })
}

export type Schemas = components['schemas']
