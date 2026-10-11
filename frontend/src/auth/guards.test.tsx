import { screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { renderWithProviders } from '../test/render'
import type { AuthState } from './context'
import { RequireAuth, RequirePermission } from './guards'
import { fakeAuth, OPERATOR } from './test-auth'

function Where() {
  const location = useLocation()
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>
}

function renderAt(path: string, state: AuthState, page = <p>secret page</p>) {
  const { Provider } = fakeAuth(state)
  return renderWithProviders(
    <Provider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<Where />} />
          <Route path="/setup/mfa" element={<Where />} />
          <Route path="/setup/password" element={<Where />} />
          <Route path="*" element={<RequireAuth>{page}</RequireAuth>} />
        </Routes>
      </MemoryRouter>
    </Provider>,
  )
}

describe('route guards', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('tr')
  })

  it('sends visitors to the login page and back to where they were going', () => {
    renderAt('/devices?q=core', { status: 'anonymous' })
    expect(screen.getByTestId('where')).toHaveTextContent('/login?next=%2Fdevices%3Fq%3Dcore')
  })

  it('lets a signed-in user through', () => {
    renderAt('/devices', { status: 'authenticated', me: OPERATOR })
    expect(screen.getByText('secret page')).toBeInTheDocument()
  })

  it('sends a session that must enroll in MFA or change its password to that page', () => {
    renderAt('/devices', {
      status: 'authenticated',
      me: { ...OPERATOR, requirements: ['mfa_enrollment'] },
    })
    expect(screen.getByTestId('where')).toHaveTextContent('/setup/mfa')
  })

  it('shows why a role cannot open an admin page', () => {
    renderAt(
      '/admin/users',
      { status: 'authenticated', me: OPERATOR },
      <RequirePermission permission="users:manage">
        <p>user list</p>
      </RequirePermission>,
    )
    expect(screen.queryByText('user list')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Bu sayfaya erişiminiz yok' })).toBeInTheDocument()
    expect(screen.getByText(/Operatör/)).toHaveTextContent('users:manage')
  })
})
