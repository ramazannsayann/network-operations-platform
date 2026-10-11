import { useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'

import { api } from '../api/client'
import { unwrap } from '../api/errors'
import { AuthContext, type AuthState, type SecondFactor, type SignIn } from './context'
import { clearSession, onSessionEnded, refreshSession, setSession } from './session'

async function fetchMe() {
  return unwrap(api.GET('/api/v1/auth/me'))
}

/** Restores the session from the refresh cookie on load and tracks sign-in and out. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const [state, setState] = useState<AuthState>({ status: 'loading' })

  const reload = useCallback(async () => {
    try {
      setState({ status: 'authenticated', me: await fetchMe() })
    } catch {
      clearSession()
      setState({ status: 'anonymous' })
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void refreshSession().then(async (ok) => {
      if (cancelled) return
      if (ok) await reload()
      else setState({ status: 'anonymous' })
    })
    const stop = onSessionEnded(() => {
      client.clear()
      setState({ status: 'anonymous' })
    })
    return () => {
      cancelled = true
      stop()
    }
  }, [client, reload])

  const login = useCallback(
    async (username: string, password: string): Promise<SignIn> => {
      const result = await unwrap(api.POST('/api/v1/auth/login', { body: { username, password } }))
      if (result.status === 'mfa_required' && result.mfa_challenge) {
        return { status: 'mfa_required', challenge: result.mfa_challenge }
      }
      if (!result.access_token) throw new Error('no access token in the answer')
      setSession({ access_token: result.access_token, expires_in: result.expires_in })
      await reload()
      return { status: 'authenticated' }
    },
    [reload],
  )

  const verifyMfa = useCallback(
    async (challenge: string, factor: SecondFactor) => {
      const grant = await unwrap(
        api.POST('/api/v1/auth/mfa/verify', { body: { mfa_challenge: challenge, ...factor } }),
      )
      setSession(grant)
      await reload()
    },
    [reload],
  )

  const logout = useCallback(async () => {
    try {
      await api.POST('/api/v1/auth/logout')
    } finally {
      clearSession()
      client.clear()
      setState({ status: 'anonymous' })
    }
  }, [client])

  const value = useMemo(
    () => ({ state, login, verifyMfa, logout, reload }),
    [state, login, verifyMfa, logout, reload],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
