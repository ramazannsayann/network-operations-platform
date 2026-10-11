import createClient from 'openapi-fetch'

import { currentToken, expiresSoon, refreshSession, sessionEnded } from '../auth/session'
import type { components, paths } from './schema'

/** Typed client for the NetOps API; paths, parameters and bodies come from the contract. */
export const api = createClient<paths>({ baseUrl: '/', credentials: 'same-origin' })

// How a client gets a token: these go out without one, and their 401 means "wrong
// credentials", not "session over".
const PUBLIC = ['/api/v1/auth/login', '/api/v1/auth/mfa/verify', '/api/v1/auth/refresh']

function isPublic(url: string): boolean {
  const path = new URL(url, window.location.origin).pathname
  return PUBLIC.includes(path) || path === '/api/health'
}

api.use({
  async onRequest({ request }) {
    if (isPublic(request.url)) return request
    if (expiresSoon()) await refreshSession()
    const token = currentToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
  onResponse({ request, response }) {
    // The session ended (logout elsewhere, revoked, deactivated): back to the sign-in page.
    if (response.status === 401 && !isPublic(request.url)) sessionEnded()
    return response
  },
})

export type Schemas = components['schemas']
