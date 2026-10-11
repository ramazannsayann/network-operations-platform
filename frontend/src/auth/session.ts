/**
 * The browser side of a session (ADR-0008).
 *
 * The access token lives only in this module's memory: never in localStorage, a cookie or
 * the URL, so a script injected into the page cannot read it from storage, and a reload
 * starts from the refresh cookie (HttpOnly, sent only to /api/v1/auth). The token is
 * refreshed shortly before it expires. Refreshes are serialized across tabs with the Web
 * Locks API: two tabs rotating the same refresh token at once would look like token theft
 * to the server, which then ends the session.
 */

const REFRESH_PATH = '/api/v1/auth/refresh'
const REFRESH_EARLY_MS = 60_000
const LOCK_NAME = 'netops-session-refresh'

export interface TokenGrant {
  access_token: string
  expires_in: number
}

let accessToken: string | null = null
let expiresAt = 0
let inFlight: Promise<boolean> | null = null
const listeners = new Set<() => void>()

export function setSession(grant: TokenGrant, now = Date.now()): void {
  accessToken = grant.access_token
  expiresAt = now + grant.expires_in * 1000
}

export function clearSession(): void {
  accessToken = null
  expiresAt = 0
}

export function currentToken(): string | null {
  return accessToken
}

export function expiresSoon(now = Date.now()): boolean {
  return accessToken !== null && expiresAt - now < REFRESH_EARLY_MS
}

/** Called when the server says the session is gone (401): sign-in again. */
export function onSessionEnded(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function sessionEnded(): void {
  clearSession()
  for (const listener of listeners) listener()
}

async function doRefresh(): Promise<boolean> {
  const response = await fetch(REFRESH_PATH, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    clearSession()
    return false
  }
  setSession((await response.json()) as TokenGrant)
  return true
}

/**
 * Get a new access token with the refresh cookie; false when there is no session. One
 * request at a time in this tab, and one at a time across tabs where Web Locks exist.
 */
export function refreshSession(): Promise<boolean> {
  if (inFlight) return inFlight
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined
  const run = locks ? locks.request(LOCK_NAME, () => doRefresh()) : doRefresh()
  inFlight = run.finally(() => {
    inFlight = null
  })
  return inFlight
}
