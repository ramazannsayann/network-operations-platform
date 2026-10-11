import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  clearSession,
  currentToken,
  expiresSoon,
  onSessionEnded,
  refreshSession,
  sessionEnded,
  setSession,
} from './session'

afterEach(() => {
  clearSession()
  vi.unstubAllGlobals()
})

describe('session', () => {
  it('keeps the access token in memory and refreshes a minute before it expires', () => {
    setSession({ access_token: 'token-1', expires_in: 900 }, 0)
    expect(currentToken()).toBe('token-1')
    expect(expiresSoon(839_000)).toBe(false)
    expect(expiresSoon(841_000)).toBe(true)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('sends one refresh at a time and stores the new token', async () => {
    let calls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        calls += 1
        await new Promise((resolve) => setTimeout(resolve, 10))
        return new Response(JSON.stringify({ access_token: 'token-2', expires_in: 900 }), {
          status: 200,
        })
      }),
    )
    const results = await Promise.all([refreshSession(), refreshSession(), refreshSession()])
    expect(results).toEqual([true, true, true])
    expect(calls).toBe(1)
    expect(currentToken()).toBe('token-2')
  })

  it('forgets the token when the refresh is refused', async () => {
    setSession({ access_token: 'old', expires_in: 900 })
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('{}', { status: 401 }))),
    )
    expect(await refreshSession()).toBe(false)
    expect(currentToken()).toBeNull()
  })

  it('tells listeners when the server ends the session', () => {
    const listener = vi.fn()
    const stop = onSessionEnded(listener)
    setSession({ access_token: 'token', expires_in: 900 })
    sessionEnded()
    expect(listener).toHaveBeenCalledOnce()
    expect(currentToken()).toBeNull()
    stop()
  })
})
