import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import { renderWithProviders } from '../../test/render'
import { passwordMessageKey } from './problems'
import { RecoveryCodes } from './RecoveryCodes'

describe('recovery codes', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('tr')
  })

  it('are shown once and the user must confirm saving them', async () => {
    const done = vi.fn()
    const codes = Array.from({ length: 10 }, (_, i) => `code${String(i)}-abcde`)
    renderWithProviders(<RecoveryCodes codes={codes} onDone={done} />)
    expect(screen.getByTestId('recovery-codes').querySelectorAll('p')).toHaveLength(10)
    expect(screen.getByText(/yalnızca şimdi gösterilir/)).toBeInTheDocument()
    const finish = screen.getByRole('button', { name: 'Bitir' })
    expect(finish).toBeDisabled()
    await userEvent.click(screen.getByLabelText('Kurtarma kodlarını güvenli bir yere kaydettim'))
    await userEvent.click(finish)
    expect(done).toHaveBeenCalledOnce()
    expect(screen.getByRole('link', { name: 'İndir (.txt)' })).toHaveAttribute(
      'download',
      'netops-recovery-codes.txt',
    )
  })
})

describe('password policy messages', () => {
  it('map the API error types to translated messages', () => {
    expect(passwordMessageKey('password.common')).toBe('account.password.errors.common')
    expect(passwordMessageKey('password.too_short')).toBe('account.password.errors.too_short')
    expect(passwordMessageKey('password.something_new')).toBe('account.password.errors.other')
    expect(i18n.t(passwordMessageKey('password.too_short'), { min: 12 })).toContain('12')
  })
})
