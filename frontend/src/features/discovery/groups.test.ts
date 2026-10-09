import { describe, expect, it } from 'vitest'

import type { Schemas } from '../../api/client'
import { groupItems } from './groups'

const item = (
  status: Schemas['DiscoveryItemStatus'],
  address: string,
): Schemas['DiscoveryRunItem'] => ({
  address,
  hop: 1,
  status,
  device: null,
  seen_from: null,
  local_interface: null,
  neighbor_name: null,
  platform: null,
  attempts: 0,
  is_new: false,
  error: null,
  occurred_at: '2026-10-10T08:00:00Z',
})

describe('discovery results', () => {
  it('group by status in a fixed order and skip empty groups', () => {
    const groups = groupItems([
      item('out_of_scope', '198.51.100.1'),
      item('discovered', '10.0.0.1'),
      item('auth_failed', '10.0.0.74'),
      item('discovered', '10.0.0.2'),
    ])
    expect(groups.map(([status, items]) => [status, items.length])).toEqual([
      ['discovered', 2],
      ['auth_failed', 1],
      ['out_of_scope', 1],
    ])
  })
})
