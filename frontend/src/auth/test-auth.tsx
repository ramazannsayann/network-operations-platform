import type { ReactNode } from 'react'
import { vi } from 'vitest'

import { AuthContext, type AuthContextValue, type AuthState, type CurrentUser } from './context'

export const OPERATOR: CurrentUser = {
  id: '5e0c7a1d-0000-4000-8000-000000007002',
  username: 'operator1',
  display_name: 'NOC Operator 1',
  email: null,
  role: 'operator',
  permissions: ['devices:read', 'devices:refresh', 'discovery:run', 'profile:self'],
  mfa_enabled: true,
  mfa_required: true,
  requirements: [],
  session_id: '5e0c7a1d-0000-4000-8000-000000007101',
  last_login_at: null,
  password_changed_at: '2026-10-01T00:00:00Z',
}

export function fakeAuth(state: AuthState, overrides: Partial<AuthContextValue> = {}) {
  const value: AuthContextValue = {
    state,
    login: vi.fn(),
    verifyMfa: vi.fn(),
    logout: vi.fn(),
    reload: vi.fn(),
    ...overrides,
  }
  return {
    value,
    Provider: ({ children }: { children: ReactNode }) => (
      <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
    ),
  }
}
