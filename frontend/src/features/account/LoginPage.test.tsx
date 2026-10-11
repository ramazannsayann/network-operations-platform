import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/errors'
import { fakeAuth } from '../../auth/test-auth'
import i18n from '../../i18n'
import { renderWithProviders } from '../../test/render'
import { LoginPage } from './LoginPage'

function renderLogin(overrides: Parameters<typeof fakeAuth>[1]) {
  const { Provider, value } = fakeAuth({ status: 'anonymous' }, overrides)
  renderWithProviders(
    <Provider>
      <MemoryRouter initialEntries={['/login?next=%2Fdevices']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/devices" element={<p>devices page</p>} />
        </Routes>
      </MemoryRouter>
    </Provider>,
  )
  return value
}

async function submitPassword() {
  await userEvent.type(screen.getByLabelText(/Kullanıcı adı/), 'operator1')
  await userEvent.type(screen.getByLabelText(/^Parola/), 'a long pass phrase')
  await userEvent.click(screen.getByRole('button', { name: 'Oturum aç' }))
}

describe('login page', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('tr')
  })

  it('signs in and goes where the user was going', async () => {
    const login = vi.fn().mockResolvedValue({ status: 'authenticated' })
    renderLogin({ login })
    await submitPassword()
    expect(login).toHaveBeenCalledWith('operator1', 'a long pass phrase')
    expect(await screen.findByText('devices page')).toBeInTheDocument()
  })

  it('asks for the TOTP code when MFA is on, or a recovery code instead', async () => {
    const login = vi.fn().mockResolvedValue({ status: 'mfa_required', challenge: 'c-1' })
    const verifyMfa = vi.fn().mockResolvedValue(undefined)
    renderLogin({ login, verifyMfa })
    await submitPassword()
    expect(await screen.findByRole('heading', { name: 'İki adımlı doğrulama' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Doğrula' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Kurtarma kodu kullan' }))
    await userEvent.type(screen.getByLabelText('Kurtarma kodu'), 'k7mfp-2wq9x')
    await userEvent.click(screen.getByRole('button', { name: 'Doğrula' }))
    expect(verifyMfa).toHaveBeenCalledWith('c-1', { recovery_code: 'k7mfp-2wq9x' })
    expect(await screen.findByText('devices page')).toBeInTheDocument()
  })

  it('shows one message for every sign-in failure and another for rate limits', async () => {
    const login = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(401, null))
      .mockRejectedValueOnce(new ApiError(429, null))
    renderLogin({ login })
    await submitPassword()
    expect(await screen.findByRole('alert')).toHaveTextContent('Kullanıcı adı veya parola hatalı')
    await userEvent.type(screen.getByLabelText(/^Parola/), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Oturum aç' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('çok fazla deneme')
    })
  })
})
