import { describe, expect, it } from 'vitest'

import {
  layoutByRole,
  mergePositions,
  SPACING,
  shortPort,
  type Topology,
  type TopologyNode,
  TIER,
  tierOf,
  toElements,
  withStatusCaptions,
} from './elements'

function device(id: string, extra: Partial<TopologyNode> = {}): TopologyNode {
  return {
    id,
    kind: 'device',
    label: id,
    device_id: `00000000-0000-4000-8000-${id.padStart(12, '0').slice(-12)}`,
    device_type: 'switch',
    role: 'access',
    location_id: null,
    reachability: 'reachable',
    is_managed: true,
    management_status: 'managed',
    out_of_scope: false,
    mgmt_ip: null,
    model: null,
    open_alarm_count: 0,
    prefix: null,
    gateway_ips: [],
    ...extra,
  }
}

const ref = (name: string, device = 'x') => ({
  id: `00000000-0000-4000-8000-0000000000${name.length}`,
  device_id: device,
  name,
})

const L2: Topology = {
  layer: 'l2',
  at: '2026-10-10T08:00:00Z',
  nodes: [
    device('isp', {
      device_type: 'router',
      role: 'unknown',
      management_status: 'out_of_scope',
      out_of_scope: true,
      is_managed: false,
    }),
    device('rtr1', { device_type: 'router', role: 'edge' }),
    device('core1', { device_type: 'l3_switch', role: 'core' }),
    device('core2', { device_type: 'l3_switch', role: 'core' }),
    device('dist1', { role: 'distribution' }),
    device('acc1'),
    device('acc4', { management_status: 'auth_failed', is_managed: false }),
    device('ap1', {
      device_type: 'ap',
      role: 'unknown',
      management_status: 'unsupported_platform',
      is_managed: false,
    }),
  ],
  edges: [
    {
      id: 'etherchannel:a:b',
      kind: 'etherchannel',
      source: 'core1',
      target: 'core2',
      source_interface: ref('Port-channel1'),
      target_interface: ref('Port-channel1'),
      link_source: 'cdp',
      is_active: true,
      members: [
        {
          link_id: 'l1',
          source_interface: ref('TenGigabitEthernet1/1/1'),
          target_interface: ref('TenGigabitEthernet1/1/1'),
          is_active: true,
        },
        {
          link_id: 'l2',
          source_interface: ref('TenGigabitEthernet1/1/2'),
          target_interface: ref('TenGigabitEthernet1/1/2'),
          is_active: false,
        },
      ],
      link_id: null,
      address: null,
      hsrp_state: null,
    },
    ...(
      [
        ['rtr1', 'isp'],
        ['core1', 'rtr1'],
        ['core1', 'dist1'],
        ['dist1', 'acc1'],
        ['dist1', 'acc4'],
        ['acc1', 'ap1'],
      ] as const
    ).map(([source, target]) => ({
      id: `${source}-${target}`,
      kind: 'link' as const,
      source,
      target,
      source_interface: ref('GigabitEthernet1/0/1'),
      target_interface: ref('GigabitEthernet1/0/49'),
      link_source: 'cdp' as const,
      is_active: true,
      members: [],
      link_id: `${source}-${target}`,
      address: null,
      hsrp_state: null,
    })),
    {
      id: 'dangling',
      kind: 'link',
      source: 'core1',
      target: 'not-in-the-graph',
      source_interface: null,
      target_interface: null,
      link_source: 'lldp',
      is_active: true,
      members: [],
      link_id: 'dangling',
      address: null,
      hsrp_state: null,
    },
  ],
}

describe('topology -> Cytoscape elements', () => {
  const elements = toElements(L2)
  const node = (id: string) => elements.nodes.find((n) => n.data.id === id)
  const edge = (id: string) => elements.edges.find((e) => e.data.id === id)

  it('keeps every node and drops edges to unknown nodes', () => {
    expect(elements.nodes).toHaveLength(8)
    expect(elements.edges).toHaveLength(7)
    expect(edge('dangling')).toBeUndefined()
  })

  it('classes nodes by type and status, and flags unmanaged ones', () => {
    expect(node('core1')?.classes).toBe('device type-l3_switch status-managed')
    expect(node('isp')?.classes).toBe('device type-router status-out_of_scope unmanaged')
    expect(node('acc4')?.classes).toContain('status-auth_failed')
    expect(node('ap1')?.classes).toContain('type-ap')
  })

  it('draws an EtherChannel as one edge with its member count', () => {
    const channel = edge('etherchannel:a:b')
    expect(channel?.data.kind).toBe('etherchannel')
    expect(channel?.data.members).toBe(2)
    expect(channel?.data.badge).toBe('1/2') // one member not seen
    expect(channel?.classes).toBe('etherchannel degraded')
    expect(channel?.data.ports).toBe('Po1 ↔ Po1')
  })

  it('shows ports on hover for plain links', () => {
    expect(edge('dist1-acc1')?.data.hoverLabel).toBe('Gi1/0/1 ↔ Gi1/0/49')
    expect(edge('dist1-acc1')?.data.badge).toBe('')
  })

  it('adds the status to the caption of unmanaged nodes', () => {
    const captioned = withStatusCaptions(elements, (status) => `<${status}>`)
    const caption = (id: string) => captioned.nodes.find((n) => n.data.id === id)?.data.display
    expect(caption('core1')).toBe('core1')
    expect(caption('acc4')).toBe('acc4\n(<auth_failed>)')
    expect(caption('isp')).toBe('isp\n(<out_of_scope>)')
  })
})

describe('L3 elements', () => {
  const l3: Topology = {
    layer: 'l3',
    at: '2026-10-10T08:00:00Z',
    nodes: [
      device('core1', { device_type: 'l3_switch', role: 'core' }),
      {
        ...device('10.10.10.0/24'),
        kind: 'subnet',
        device_id: null,
        device_type: null,
        role: null,
        management_status: null,
        prefix: '10.10.10.0/24',
        gateway_ips: ['10.10.10.1'],
      },
    ],
    edges: [
      {
        id: 'member:x:10.10.10.0/24',
        kind: 'subnet_member',
        source: 'core1',
        target: '10.10.10.0/24',
        source_interface: ref('Vlan10'),
        target_interface: null,
        link_source: null,
        is_active: true,
        members: [],
        link_id: null,
        address: '10.10.10.2/24',
        hsrp_state: 'active',
      },
    ],
  }

  it('maps subnets and marks the active HSRP router', () => {
    const elements = toElements(l3)
    const subnet = elements.nodes.find((n) => n.data.kind === 'subnet')
    expect(subnet?.classes).toBe('subnet type-subnet status-subnet')
    expect(subnet?.data.gateways).toBe('10.10.10.1')
    const member = elements.edges[0]
    expect(member?.classes).toBe('subnet_member hsrp-active')
    expect(member?.data.badge).toBe('HSRP active')
    expect(member?.data.ports).toBe('Vl10 10.10.10.2/24')
  })

  it('puts a subnet just below a single-row membership', () => {
    const positions = layoutByRole(toElements(l3))
    expect(positions['10.10.10.0/24']?.y).toBeCloseTo((TIER.core + 1.5) * SPACING.y)
  })
})

describe('layout by role', () => {
  it('ranks nodes: out of scope, edge, core, distribution, access, endpoints', () => {
    const tiers = Object.fromEntries(L2.nodes.map((n) => [n.label, tierOf(n)]))
    expect(tiers).toEqual({
      isp: TIER.outOfScope,
      rtr1: TIER.edge,
      core1: TIER.core,
      core2: TIER.core,
      dist1: TIER.distribution,
      acc1: TIER.access,
      acc4: TIER.access,
      ap1: TIER.endpoint,
    })
  })

  it('places tiers in rows from top to bottom, centred', () => {
    const positions = layoutByRole(toElements(L2))
    expect(positions.isp?.y).toBeLessThan(positions.rtr1?.y ?? 0)
    expect(positions.rtr1?.y).toBeLessThan(positions.core1?.y ?? 0)
    expect(positions.core1?.y).toBe(positions.core2?.y)
    expect(positions.dist1?.y).toBeLessThan(positions.acc1?.y ?? 0)
    expect(positions.acc1?.y).toBeLessThan(positions.ap1?.y ?? 0)
    expect((positions.core1?.x ?? 0) + (positions.core2?.x ?? 0)).toBe(0)
  })

  it('prefers saved positions for known nodes', () => {
    const merged = mergePositions({ a: { x: 0, y: 0 }, b: { x: 1, y: 1 } }, [
      { node_id: 'a', x: 50, y: 60 },
      { node_id: 'gone', x: 9, y: 9 },
    ])
    expect(merged).toEqual({ a: { x: 50, y: 60 }, b: { x: 1, y: 1 } })
  })
})

describe('port names', () => {
  it.each([
    ['GigabitEthernet1/0/1', 'Gi1/0/1'],
    ['TenGigabitEthernet1/1/1', 'Te1/1/1'],
    ['Port-channel1', 'Po1'],
    ['Vlan10', 'Vl10'],
    ['mgmt0', 'mgmt0'],
  ])('%s -> %s', (name, short) => {
    expect(shortPort(name)).toBe(short)
  })
})
