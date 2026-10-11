import { Center, Loader } from '@mantine/core'
import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'

import { ForbiddenPage } from './ForbiddenPage'
import { type Permission, useAuth, useCan } from './context'

const SETUP = { password_change: '/setup/password', mfa_enrollment: '/setup/mfa' } as const

/**
 * Signed-in users only. A session that must first change its password or enroll in MFA
 * is sent to that page (the API refuses everything else to it anyway).
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useAuth()
  const location = useLocation()
  if (state.status === 'loading') {
    return (
      <Center h="100vh">
        <Loader aria-label="…" />
      </Center>
    )
  }
  if (state.status === 'anonymous') {
    const next = `${location.pathname}${location.search}`
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />
  }
  const pending = state.me.requirements[0]
  if (pending && location.pathname !== SETUP[pending]) {
    return <Navigate to={SETUP[pending]} replace />
  }
  return children
}

/** A page for roles with ``permission``; others see why they cannot use it. */
export function RequirePermission({
  permission,
  children,
}: {
  permission: Permission
  children: ReactNode
}) {
  return useCan(permission) ? children : <ForbiddenPage permission={permission} />
}
