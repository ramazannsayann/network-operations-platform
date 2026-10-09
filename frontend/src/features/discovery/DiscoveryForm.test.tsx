import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import { renderWithProviders } from '../../test/render'
import { DiscoveryForm } from './DiscoveryPage'

const mutate = vi.fn()

vi.mock('../../api/queries', () => ({
  useCredentialProfiles: () => ({
    data: {
      items: [{ id: '5e0c7a1d-0000-4000-8000-000000008001', name: 'campus-ro', kind: 'ssh' }],
      total: 1,
      limit: 500,
      offset: 0,
    },
    isPending: false,
    isError: false,
  }),
  useStartDiscovery: () => ({ mutate, isPending: false, isError: false }),
  useDiscoveryRuns: () => ({ data: undefined, isPending: true, isError: false }),
}))

/** The visible text field of a Mantine TagsInput (a hidden input carries the same label). */
function tagsInput(label: RegExp): HTMLElement {
  const input = screen
    .getAllByLabelText(label)
    .find((element) => element instanceof HTMLInputElement && element.type !== 'hidden')
  if (!input) throw new Error(`no text input labelled ${String(label)}`)
  return input
}

function renderForm() {
  return renderWithProviders(
    <MemoryRouter>
      <DiscoveryForm />
    </MemoryRouter>,
  )
}

describe('discovery form', () => {
  beforeEach(async () => {
    mutate.mockReset()
    await i18n.changeLanguage('tr')
  })

  it('shows every problem on submit and sends nothing', async () => {
    renderForm()
    await userEvent.click(screen.getByRole('button', { name: 'Keşfi başlat' }))
    expect(screen.getByText('En az bir başlangıç adresi girin.')).toBeInTheDocument()
    expect(screen.getByText('En az bir alt ağ girin.')).toBeInTheDocument()
    expect(screen.getByText('En az bir kimlik bilgisi profili seçin.')).toBeInTheDocument()
    expect(mutate).not.toHaveBeenCalled()
  })

  it('rejects an invalid address and an invalid network', async () => {
    renderForm()
    await userEvent.type(tagsInput(/Başlangıç adresleri/), '10.0.0.300,')
    await userEvent.type(tagsInput(/İzin verilen alt ağlar/), '10.0.0.0,')
    await userEvent.click(screen.getByRole('button', { name: 'Keşfi başlat' }))
    expect(screen.getByText('Geçersiz IP adresi.')).toBeInTheDocument()
    expect(screen.getByText('Geçersiz CIDR (örnek: 10.0.0.0/16).')).toBeInTheDocument()
    expect(mutate).not.toHaveBeenCalled()
  })
})
