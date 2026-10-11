import { describe, expect, it } from 'vitest'

import {
  layoutByRole,
  mergePositions,
  SPACING,
  spread,
  shortGateway,
  shortPort,
  type Topology,
  type TopologyEdge,
  type TopologyNode,
  TIER,
  tierOf,
  toElements,
  withoutManagementSubnets,
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
    management_subnet: false,
    ...extra,
  }
}

function subnet(prefix: string, extra: Partial<TopologyNode> = {}): TopologyNode {
  return device(prefix, {
    kind: 'subnet',
    device_id: null,
    device_type: null,
    role: null,
    management_status: null,
    prefix,
    ...extra,
  })
}

const ref = (name: string, owner = 'x') => ({
  id: `00000000-0000-4000-8000-0000000000${name.length}`,
  device_id: owner,
  name,
})

function link(source: string, target: string): TopologyEdge {
  return {
    id: `${source}-${target}`,
    kind: 'link',
    source,
    target,
    source_interface: ref('GigabitEthernet1/0/1'),
    target_interface: ref('GigabitEthernet1/0/49'),
    link_source: 'cdp',
    is_active: true,
    members: [],
    link_id: `${source}-${target}`,
    address: null,
    hsrp_state: null,
  }
}

function member(
  source: string,
  target: string,
  hsrp: TopologyEdge['hsrp_state'],
  address = '10.10.10.2/24',
): TopologyEdge {
  return {
    ...link(source, target),
    id: `member:${source}:${target}`,
    kind: 'subnet_member',
    source_interface: ref('Vlan10'),
    target_interface: null,
    link_source: null,
    link_id: null,
    address,
    hsrp_state: hsrp,
  }
}

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
    device('fw', { device_type: 'firewall', role: 'edge' }),
    device('odd', { device_type: 'wlc', role: 'unknown', management_status: 'manual' }),
  ],
  edges: [
    {
      ...link('core1', 'core2'),
      id: 'etherchannel:a:b',
      kind: 'etherchannel',
      source_interface: ref('Port-channel1'),
      target_interface: ref('Port-channel1'),
      link_id: null,
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
    },
    link('rtr1', 'isp'),
    link('core1', 'rtr1'),
    link('core1', 'dist1'),
    link('dist1', 'acc1'),
    link('dist1', 'acc4'),
    link('acc1', 'ap1'),
    { ...link('core1', 'not-in-the-graph'), id: 'dangling' },
  ],
}

describe('topology -> Cytoscape elements (L2)', () => {
  const elements = toElements(L2)
  const node = (id: string) => elements.nodes.find((n) => n.data.id === id)
  const edge = (id: string) => elements.edges.find((e) => e.data.id === id)

  it('keeps every node and drops edges to unknown nodes', () => {
    expect(elements.nodes).toHaveLength(10)
    expect(elements.edges).toHaveLength(7)
    expect(edge('dangling')).toBeUndefined()
  })

  it('gives each device type its own class (shape and icon), unknown types as unknown', () => {
    expect(node('core1')?.classes).toBe('device type-l3_switch status-managed')
    expect(node('rtr1')?.data.deviceType).toBe('router')
    expect(node('acc1')?.data.deviceType).toBe('switch')
    expect(node('ap1')?.data.deviceType).toBe('ap')
    expect(node('fw')?.data.deviceType).toBe('firewall')
    expect(node('odd')?.data.deviceType).toBe('wlc')
    expect(node('isp')?.classes).toBe('device type-router status-out_of_scope')
    expect(node('acc4')?.classes).toContain('status-auth_failed')
  })

  it('draws an EtherChannel as one edge whose only label is the member count', () => {
    const channel = edge('etherchannel:a:b')
    expect(channel?.data.kind).toBe('etherchannel')
    expect(channel?.data.members).toBe(2)
    expect(channel?.data.badge).toBe('1/2') // one member not seen
    expect(channel?.classes).toBe('etherchannel degraded')
    expect(channel?.data.tooltip).toBe('Po1 ↔ Po1 · Te1/1/1 ↔ Te1/1/1, Te1/1/2 ↔ Te1/1/2 (–)')
  })

  it('puts ports in the hover tooltip, not on the edge', () => {
    expect(edge('dist1-acc1')?.data.badge).toBe('')
    expect(edge('dist1-acc1')?.data.tooltip).toBe('Gi1/0/1 ↔ Gi1/0/49')
  })

  it('adds a short status line to the caption of devices not managed', () => {
    const captioned = withStatusCaptions(elements, (status) => `<${status}>`)
    const caption = (id: string) => captioned.nodes.find((n) => n.data.id === id)?.data.display
    expect(caption('core1')).toBe('core1')
    expect(caption('odd')).toBe('odd') // manual: nothing to say
    expect(caption('acc4')).toBe('acc4\n(<auth_failed>)')
    expect(caption('ap1')).toBe('ap1\n(<unsupported_platform>)')
  })
})

describe('L3 elements', () => {
  const l3: Topology = {
    layer: 'l3',
    at: '2026-10-10T08:00:00Z',
    nodes: [
      device('rtr1', { device_type: 'router', role: 'edge' }),
      device('core1', { device_type: 'l3_switch', role: 'core' }),
      device('core2', { device_type: 'l3_switch', role: 'core' }),
      subnet('10.10.10.0/24', { gateway_ips: ['10.10.10.1'] }),
      subnet('10.10.20.0/24', { gateway_ips: ['10.10.20.1'] }),
      subnet('10.255.0.0/27', { gateway_ips: ['10.255.0.1'], management_subnet: true }),
      subnet('10.255.0.192/30'),
    ],
    edges: [
      member('core1', '10.10.10.0/24', 'active'),
      member('core2', '10.10.10.0/24', 'standby', '10.10.10.3/24'),
      member('core1', '10.10.20.0/24', 'standby'),
      member('core2', '10.10.20.0/24', 'active'),
      member('core1', '10.255.0.0/27', 'active'),
      member('core2', '10.255.0.0/27', 'standby'),
      member('rtr1', '10.255.0.192/30', null, '10.255.0.194/30'),
      member('core1', '10.255.0.192/30', null, '10.255.0.193/30'),
    ],
  }
  const elements = toElements(l3)
  const node = (id: string) => elements.nodes.find((n) => n.data.id === id)
  const edge = (id: string) => elements.edges.find((e) => e.data.id === id)

  it('names the gateway and its active router in the subnet caption', () => {
    expect(node('10.10.10.0/24')?.data.display).toBe('10.10.10.0/24 · GW .1 (core1)')
    expect(node('10.10.20.0/24')?.data.display).toBe('10.10.20.0/24 · GW .1 (core2)')
    expect(node('10.255.0.192/30')?.data.display).toBe('10.255.0.192/30') // no HSRP
    expect(node('10.10.10.0/24')?.data.tooltip).toBe(
      '10.10.10.0/24 · GW 10.10.10.1\nHSRP core1 active\nHSRP core2 standby',
    )
  })

  it('shows HSRP roles by edge style and tooltip, never as edge text', () => {
    for (const { data } of elements.edges) expect(data.badge).toBe('')
    expect(edge('member:core1:10.10.10.0/24')?.classes).toBe('subnet_member hsrp-active')
    expect(edge('member:core2:10.10.10.0/24')?.classes).toBe('subnet_member hsrp-standby')
    expect(edge('member:rtr1:10.255.0.192/30')?.classes).toBe('subnet_member')
    expect(edge('member:core1:10.10.10.0/24')?.data.tooltip).toBe(
      'Vl10 10.10.10.2/24 · HSRP active',
    )
  })

  it('marks management subnets, which can be hidden with their edges', () => {
    expect(node('10.255.0.0/27')?.classes).toContain('management')
    const hidden = withoutManagementSubnets(elements)
    expect(hidden.nodes.map((n) => n.data.id)).not.toContain('10.255.0.0/27')
    expect(hidden.edges.some((e) => e.data.target === '10.255.0.0/27')).toBe(false)
    expect(hidden.nodes).toHaveLength(6)
  })

  it('places subnets under their active gateway, management subnets in a lower row', () => {
    const positions = layoutByRole(elements)
    const x = (id: string) => positions[id]?.x ?? NaN
    const y = (id: string) => positions[id]?.y ?? NaN
    // Each user subnet leans towards its gateway: VLAN 10 to core1, VLAN 20 to core2.
    expect(x('core1')).toBeLessThan(x('core2'))
    expect(x('10.10.10.0/24')).toBeLessThan(x('10.10.20.0/24'))
    expect(Math.abs(x('10.10.10.0/24') - x('core1'))).toBeLessThan(
      Math.abs(x('10.10.10.0/24') - x('core2')),
    )
    expect(Math.abs(x('10.10.20.0/24') - x('core2'))).toBeLessThan(
      Math.abs(x('10.10.20.0/24') - x('core1')),
    )
    expect(y('10.10.10.0/24')).toBeGreaterThan(y('core1'))
    expect(y('10.255.0.0/27') - y('10.10.10.0/24')).toBeCloseTo(SPACING.y) // its own row
    // A point-to-point subnet sits between its two ends.
    expect(y('10.255.0.192/30')).toBeGreaterThan(y('rtr1'))
    expect(y('10.255.0.192/30')).toBeLessThan(y('core1'))
  })
})

describe('layout by role', () => {
  it('ranks nodes: out of scope, edge, core, distribution, access, endpoints', () => {
    const tiers = Object.fromEntries(L2.nodes.slice(0, 8).map((n) => [n.label, tierOf(n)]))
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

  it('places tiers in rows from top to bottom, children under their parent', () => {
    const positions = layoutByRole(toElements(L2))
    const p = (id: string) => positions[id] ?? { x: NaN, y: NaN }
    expect(p('isp').y).toBeLessThan(p('rtr1').y)
    expect(p('rtr1').y).toBeLessThan(p('core1').y)
    expect(p('core1').y).toBe(p('core2').y)
    expect(p('dist1').y).toBeLessThan(p('acc1').y)
    expect(p('acc1').y).toBeLessThan(p('ap1').y)
    expect(p('ap1').x).toBeCloseTo(p('acc1').x) // the AP right under its switch
    expect(Math.abs(p('acc1').x - p('acc4').x)).toBeGreaterThanOrEqual(SPACING.minX)
  })

  it('spreads columns further on a wider canvas', () => {
    const narrow = layoutByRole(toElements(L2), 0.2)
    const wide = layoutByRole(toElements(L2), 3)
    const spread = (positions: Record<string, { x: number }>) =>
      Math.abs((positions.acc1?.x ?? 0) - (positions.acc4?.x ?? 0))
    expect(spread(wide)).toBeGreaterThan(spread(narrow))
    expect(spread(wide)).toBeLessThanOrEqual(SPACING.maxX + 0.001)
  })

  it('prefers saved positions for known nodes', () => {
    const merged = mergePositions({ a: { x: 0, y: 0 }, b: { x: 1, y: 1 } }, [
      { node_id: 'a', x: 50, y: 60 },
      { node_id: 'gone', x: 9, y: 9 },
    ])
    expect(merged).toEqual({ a: { x: 50, y: 60 }, b: { x: 1, y: 1 } })
  })
})

describe('names', () => {
  it.each([
    ['GigabitEthernet1/0/1', 'Gi1/0/1'],
    ['TenGigabitEthernet1/1/1', 'Te1/1/1'],
    ['Port-channel1', 'Po1'],
    ['Vlan10', 'Vl10'],
    ['mgmt0', 'mgmt0'],
  ])('%s -> %s', (name, short) => {
    expect(shortPort(name)).toBe(short)
  })

  it('shortens gateways inside /24 and longer prefixes only', () => {
    expect(shortGateway('10.10.10.1', '10.10.10.0/24')).toBe('.1')
    expect(shortGateway('10.255.0.65', '10.255.0.64/26')).toBe('.65')
    expect(shortGateway('10.10.0.1', '10.10.0.0/20')).toBe('10.10.0.1')
    expect(shortGateway('2001:db8::1', '2001:db8::/64')).toBe('2001:db8::1')
  })
})

describe('node icons', () => {
  it('are generic Tabler outlines, coloured for the theme', async () => {
    const { iconDataUri } = await import('./icons')
    const uri = decodeURIComponent(iconDataUri('router', '#364fc7'))
    expect(uri.startsWith('data:image/svg+xml;utf8,<svg')).toBe(true)
    expect(uri).toContain('xmlns="http://www.w3.org/2000/svg"')
    expect(uri).toContain('stroke="#364fc7"')
    expect(uri).not.toContain('currentColor')
    expect(iconDataUri('no-such-type', '#000')).toBe(iconDataUri('unknown', '#000'))
  })
})

describe('spreading a row', () => {
  it('keeps nodes where they want to be when there is room', () => {
    expect(spread([-300, 0, 300], 100)).toEqual([-300, 0, 300])
  })
  it('centres nodes that want the same spot on it', () => {
    expect(spread([0, 0, 0], 100)).toEqual([-100, 0, 100])
    expect(spread([-180, -180, 180, 180], 360)).toEqual([-540, -180, 180, 540])
  })
  it('pushes overlapping groups apart without drifting to one side', () => {
    const xs = spread([-180, 180, 180], 360)
    expect(xs[1]).toBeGreaterThan(0)
    for (let i = 1; i < xs.length; i++)
      expect((xs[i] ?? 0) - (xs[i - 1] ?? 0)).toBeGreaterThanOrEqual(359.999)
    // Neither pinned to the left node nor pushed off to the right.
    expect(xs).toEqual([-270, 90, 450])
  })
})
