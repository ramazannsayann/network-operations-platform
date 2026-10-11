import { screen } from '@testing-library/react'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import type { Schemas } from '../api/client'
import i18n from '../i18n'
import { renderWithProviders } from '../test/render'
import { ItemStatusBadge, ManagementStatusBadge } from './StatusBadges'
import { ITEM_STATUS, MANAGEMENT_STATUS } from './statusLooks'

const STATUSES: Schemas['ManagementStatus'][] = [
  'managed',
  'out_of_scope',
  'auth_failed',
  'unreachable',
  'unsupported_platform',
  'manual',
]

describe('status badges', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('tr')
  })
  afterAll(async () => {
    await i18n.changeLanguage('tr')
  })

  it.each(STATUSES)('%s has an icon and a text, not only a colour', (status) => {
    const { container } = renderWithProviders(<ManagementStatusBadge status={status} />)
    const text = i18n.t(`enums.managementStatus.${status}`)
    expect(text).not.toBe(`enums.managementStatus.${status}`)
    expect(screen.getByText(text)).toBeInTheDocument()
    expect(container.querySelector('svg')).not.toBeNull()
  })

  it('speaks Turkish by default and English on request', async () => {
    renderWithProviders(<ManagementStatusBadge status="auth_failed" />)
    expect(screen.getByText('Kimlik doğrulama başarısız')).toBeInTheDocument()
    await i18n.changeLanguage('en')
    renderWithProviders(<ItemStatusBadge status="duplicate" />)
    expect(screen.getByText('Another address of the same device')).toBeInTheDocument()
  })

  it('shows endpoints seen via CDP/LLDP as a neutral state', async () => {
    await i18n.changeLanguage('tr')
    renderWithProviders(<ManagementStatusBadge status="unsupported_platform" seenVia="cdp" />)
    expect(screen.getByText('Uç cihaz (CDP ile görüldü)')).toBeInTheDocument()
    renderWithProviders(<ManagementStatusBadge status="unsupported_platform" />)
    expect(screen.getByText('Uç cihaz (CDP/LLDP ile görüldü)')).toBeInTheDocument()
  })

  it('keeps warning and error colours for real problems', () => {
    const alarming = (looks: Record<string, { color: string }>) =>
      Object.entries(looks)
        .filter(([, look]) => ['red', 'orange', 'yellow'].includes(look.color))
        .map(([status]) => status)
        .sort()
    expect(alarming(MANAGEMENT_STATUS)).toEqual(['auth_failed', 'unreachable'])
    expect(alarming(ITEM_STATUS)).toEqual(['auth_failed', 'unreachable'])
  })
})
