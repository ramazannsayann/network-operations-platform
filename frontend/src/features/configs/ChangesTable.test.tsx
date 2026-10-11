import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it } from 'vitest'

import type { Schemas } from '../../api/client'
import i18n from '../../i18n'
import { renderWithProviders } from '../../test/render'
import { ChangesTable } from './ChangesTable'

const DEVICE = {
  id: '5e0c7a1d-0000-4000-8000-000000002003',
  hostname: 'dist1',
  mgmt_ip: '10.255.0.11',
}

const REPORTED: Schemas['ConfigChange'] = {
  id: '5e0c7a1d-0000-4000-8000-000000006101',
  device: DEVICE,
  detected_at: '2026-10-10T12:00:01Z',
  origin: 'external',
  username: 'jdoe',
  source_ip: '192.0.2.77',
  commands: [
    'interface GigabitEthernet1/0/2',
    'switchport trunk allowed vlan remove 20',
    'interface GigabitEthernet1/0/3',
    'description uplink',
    'snmp-server community <redacted> RO',
  ],
  before_version_id: '5e0c7a1d-0000-4000-8000-000000006001',
  after_version_id: '5e0c7a1d-0000-4000-8000-000000006002',
  detected_by: 'change_event',
}
const UNREPORTED: Schemas['ConfigChange'] = {
  ...REPORTED,
  id: '5e0c7a1d-0000-4000-8000-000000006102',
  username: null,
  source_ip: null,
  commands: [],
  detected_by: 'scheduled',
}

function renderTable(items: Schemas['ConfigChange'][], showDevice = true) {
  return renderWithProviders(
    <MemoryRouter>
      <ChangesTable items={items} showDevice={showDevice} />
    </MemoryRouter>,
  )
}

describe('config change list', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('tr')
  })

  it('marks external changes and shows who, from where and what', async () => {
    renderTable([REPORTED])
    const row = screen.getAllByRole('row')[1] as HTMLElement
    expect(within(row).getByText('Platform dışı değişiklik')).toBeInTheDocument()
    expect(within(row).getByText('jdoe')).toBeInTheDocument()
    expect(within(row).getByText('192.0.2.77')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'dist1' })).toHaveAttribute(
      'href',
      `/devices/${DEVICE.id}?tab=config`,
    )
    expect(within(row).getByRole('link', { name: 'Farkı göster' })).toHaveAttribute(
      'href',
      `/devices/${DEVICE.id}?tab=config&view=diff&from=${REPORTED.before_version_id ?? ''}&to=${REPORTED.after_version_id ?? ''}`,
    )
    // Three commands at first, the rest on request.
    expect(row).toHaveTextContent('switchport trunk allowed vlan remove 20')
    expect(row).not.toHaveTextContent('description uplink')
    await userEvent.click(within(row).getByRole('button', { name: '+2 komut daha' }))
    expect(row).toHaveTextContent('description uplink')
    expect(row).toHaveTextContent('snmp-server community <redacted> RO')
  })

  it('says how a change nobody reported was found', () => {
    renderTable([UNREPORTED], false)
    const row = screen.getAllByRole('row')[1] as HTMLElement
    expect(within(row).getByText('bilinmiyor')).toBeInTheDocument()
    expect(within(row).getByText('zamanlanmış yedekte bulundu')).toBeInTheDocument()
    expect(within(row).queryByRole('link', { name: 'dist1' })).toBeNull()
  })
})
