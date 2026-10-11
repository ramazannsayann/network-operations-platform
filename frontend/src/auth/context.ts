import { createContext, useContext } from 'react'

import type { Schemas } from '../api/client'

export type CurrentUser = Schemas['CurrentUser']
export type Permission = Schemas['Permission']

export type AuthState =
  { status: 'loading' } | { status: 'anonymous' } | { status: 'authenticated'; me: CurrentUser }

export type SignIn = { status: 'authenticated' } | { status: 'mfa_required'; challenge: string }

export type SecondFactor = { code: string } | { recovery_code: string }

export interface AuthContextValue {
  state: AuthState
  login: (username: string, password: string) => Promise<SignIn>
  verifyMfa: (challenge: string, factor: SecondFactor) => Promise<void>
  logout: () => Promise<void>
  /** Read the signed-in user again (after a password change, MFA enrollment, ...). */
  reload: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (value === null) throw new Error('useAuth needs an <AuthProvider>')
  return value
}

/** The signed-in user; only inside <RequireAuth>. */
export function useMe(): CurrentUser {
  const { state } = useAuth()
  if (state.status !== 'authenticated') throw new Error('useMe needs a signed-in user')
  return state.me
}

/** Whether the signed-in user's role has ``permission`` (the API enforces it anyway). */
export function useCan(permission: Permission): boolean {
  const { state } = useAuth()
  return state.status === 'authenticated' && state.me.permissions.includes(permission)
}
