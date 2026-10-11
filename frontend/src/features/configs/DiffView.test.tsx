import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../../i18n'
import { renderWithProviders } from '../../test/render'
import { ConfigViewer } from './ConfigViewer'
import { DiffView } from './DiffView'

// A secret changed: the API sends both lines redacted, and they still differ as lines.
const SECRET_CHANGED = `--- core1 @ 2026-10-10T02:30:00Z
+++ core1 @ 2026-10-10T12:00:31Z
@@ -40,3 +40,3 @@
 !
-enable secret 9 <redacted>
+enable secret 9 <redacted>
 !
`

describe('diff view', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('tr')
  })

  it('shows a changed secret as a removed and an added line, both redacted', () => {
    renderWithProviders(<DiffView text={SECRET_CHANGED} added={1} removed={1} mode="unified" />)
    const removed = document.querySelector('tr[data-change="del"]')
    const added = document.querySelector('tr[data-change="add"]')
    expect(removed).not.toBeNull()
    expect(added).not.toBeNull()
    for (const row of [removed, added] as HTMLElement[]) {
      expect(row).toHaveTextContent('enable secret 9')
      expect(within(row).getByRole('img', { name: 'gizli' })).toHaveAttribute(
        'data-redacted',
        'secret',
      )
      expect(row).not.toHaveTextContent('<redacted>')
    }
    expect(within(removed as HTMLElement).getByLabelText('Silindi')).toBeInTheDocument()
    expect(within(added as HTMLElement).getByLabelText('Eklendi')).toBeInTheDocument()
    expect(screen.getByText('+1 satır')).toBeInTheDocument()
    expect(screen.getByText('−1 satır')).toBeInTheDocument()
    expect(screen.getByText(/core1 @ 2026-10-10T02:30:00Z → core1 @/)).toBeInTheDocument()
  })

  it('puts the removed line next to the added one side by side', () => {
    renderWithProviders(<DiffView text={SECRET_CHANGED} added={1} removed={1} mode="split" />)
    expect(screen.getByRole('table', { name: 'Yan yana' })).toBeInTheDocument()
    const rows = document.querySelectorAll('tr[data-row="split"]')
    expect(rows).toHaveLength(3) // context, changed pair, context
    const pair = rows[1] as HTMLElement
    expect(within(pair).getAllByRole('img', { name: 'gizli' })).toHaveLength(2)
    expect(within(pair).getByLabelText('Silindi')).toBeInTheDocument()
    expect(within(pair).getByLabelText('Eklendi')).toBeInTheDocument()
  })

  it('says when the versions are identical', () => {
    renderWithProviders(<DiffView text="" added={0} removed={0} mode="split" />)
    expect(screen.getByText('İki sürüm aynı.')).toBeInTheDocument()
  })

  it('labels the markers in English too', async () => {
    await i18n.changeLanguage('en')
    renderWithProviders(<DiffView text={SECRET_CHANGED} added={1} removed={1} mode="unified" />)
    expect(screen.getAllByRole('img', { name: 'hidden' })).toHaveLength(2)
  })
})

describe('config viewer', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('tr')
  })

  it('numbers the lines and shows markers instead of secrets', () => {
    renderWithProviders(
      <ConfigViewer
        content={
          'hostname core1\n!\nsnmp-server community <redacted> RO\n' +
          'crypto pki certificate chain TP\n certificate 01\n  <certificate redacted>\nend\n'
        }
      />,
    )
    const table = screen.getByRole('table', { name: 'Konfigürasyon' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(7)
    expect(rows[2]).toHaveTextContent('3snmp-server community gizli RO')
    expect(within(table).getByRole('img', { name: 'gizli' })).toBeInTheDocument()
    expect(within(table).getByRole('img', { name: 'sertifika gizlendi' })).toHaveAttribute(
      'data-redacted',
      'cert',
    )
    expect(table).not.toHaveTextContent('<redacted>')
  })
})
