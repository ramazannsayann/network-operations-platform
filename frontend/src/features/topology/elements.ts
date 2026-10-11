/**
 * Topology API data -> Cytoscape elements, and the automatic layout by role.
 *
 * Pure functions (no Cytoscape instance), so they are unit tested on their own.
 */
import type { Schemas } from '../../api/client'

export type Topology = Schemas['Topology']
export type TopologyNode = Schemas['TopologyNode']
export type TopologyEdge = Schemas['TopologyEdge']
export type ManagementStatus = Schemas['ManagementStatus']

export interface Position {
  x: number
  y: number
}

/** Data carried by a Cytoscape node; read by the stylesheet, tooltips and the side panel. */
export interface MapNodeData {
  id: string
  label: string
  /** The node's caption on the map: label, plus a status line for unmanaged devices and the
   * gateway for subnets. */
  display: string
  /** Hover text. */
  tooltip: string
  kind: 'device' | 'subnet'
  deviceType: string
  role: string
  status: ManagementStatus | 'subnet'
  tier: number
  mgmtIp: string
  model: string
  gateways: string
  /** Subnets: the subnet holds devices' management addresses. */
  management: boolean
  /** Subnets: the device that is the active HSRP gateway, if any. */
  anchor: string
}

export interface MapEdgeData {
  id: string
  source: string
  target: string
  kind: TopologyEdge['kind']
  /** Always shown on the edge: the member count of an EtherChannel (nothing else). */
  badge: string
  /** Local and remote ports (L2), interface and address (L3). */
  ports: string
  /** Hover text: ports, plus HSRP state or EtherChannel members. */
  tooltip: string
  members: number
  activeMembers: number
}

export interface MapElements {
  nodes: { data: MapNodeData; classes: string }[]
  edges: { data: MapEdgeData; classes: string }[]
}

/** Vertical rank on the map: out of scope, edge, core, distribution, access, endpoints. */
export const TIER = {
  outOfScope: 0,
  edge: 1,
  core: 2,
  distribution: 3,
  access: 4,
  endpoint: 5,
} as const

/** Device types with their own shape and icon on the map; others are drawn as "unknown". */
export const MAP_DEVICE_TYPES = ['router', 'l3_switch', 'switch', 'ap', 'firewall', 'wlc'] as const

export function tierOf(node: TopologyNode): number {
  if (node.out_of_scope || node.management_status === 'out_of_scope') return TIER.outOfScope
  if (node.device_type === 'ap' || node.management_status === 'unsupported_platform')
    return TIER.endpoint
  switch (node.role) {
    case 'edge':
      return TIER.edge
    case 'core':
      return TIER.core
    case 'distribution':
      return TIER.distribution
    case 'access':
      return TIER.access
    default:
      return node.device_type === 'router' ? TIER.edge : TIER.endpoint
  }
}

/** Short interface names for labels: GigabitEthernet1/0/1 -> Gi1/0/1. */
export function shortPort(name: string | undefined | null): string {
  if (!name) return '?'
  const abbreviations: [RegExp, string][] = [
    [/^TwentyFiveGigE/, 'Twe'],
    [/^HundredGigE/, 'Hu'],
    [/^FortyGigabitEthernet/, 'Fo'],
    [/^TenGigabitEthernet/, 'Te'],
    [/^FiveGigabitEthernet/, 'Fi'],
    [/^TwoGigabitEthernet/, 'Tw'],
    [/^GigabitEthernet/, 'Gi'],
    [/^FastEthernet/, 'Fa'],
    [/^Port-channel/, 'Po'],
    [/^Vlan/, 'Vl'],
    [/^Loopback/, 'Lo'],
  ]
  for (const [pattern, short] of abbreviations) {
    if (pattern.test(name)) return name.replace(pattern, short)
  }
  return name
}

/** The gateway as engineers write it inside its subnet: ".1" for 10.10.10.1 in a /24. */
export function shortGateway(gateway: string, prefix: string | null | undefined): string {
  const length = Number((prefix ?? '').split('/')[1] ?? 0)
  const octets = gateway.split('.')
  return octets.length === 4 && length >= 24 ? `.${octets[3] ?? ''}` : gateway
}

function deviceType(node: TopologyNode): string {
  if (node.kind === 'subnet') return 'subnet'
  const type = node.device_type ?? 'unknown'
  return (MAP_DEVICE_TYPES as readonly string[]).includes(type) ? type : 'unknown'
}

export function toElements(topology: Topology): MapElements {
  const ids = new Set(topology.nodes.map((node) => node.id))
  const labels = new Map(topology.nodes.map((node) => [node.id, node.label]))
  const edges = topology.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target))

  // L3: who is the active HSRP gateway of each subnet, and every device's state there.
  const activeGateway = new Map<string, string>()
  const hsrpStates = new Map<string, string[]>()
  for (const edge of edges) {
    if (edge.kind !== 'subnet_member' || !edge.hsrp_state) continue
    if (edge.hsrp_state === 'active') activeGateway.set(edge.target, edge.source)
    hsrpStates.set(edge.target, [
      ...(hsrpStates.get(edge.target) ?? []),
      `${labels.get(edge.source) ?? '?'} ${edge.hsrp_state}`,
    ])
  }

  const nodes = topology.nodes.map((node) => {
    const isSubnet = node.kind === 'subnet'
    const gateways = node.gateway_ips ?? []
    const anchor = activeGateway.get(node.id) ?? ''
    let display = node.label
    let tooltip = [node.label, node.mgmt_ip, node.model].filter(Boolean).join(' · ')
    if (isSubnet && gateways[0]) {
      const router = anchor ? ` (${labels.get(anchor) ?? '?'})` : ''
      display = `${node.label} · GW ${shortGateway(gateways[0], node.prefix)}${router}`
      tooltip = [
        `${node.label} · GW ${gateways.join(', ')}`,
        ...(hsrpStates.get(node.id) ?? []).map((state) => `HSRP ${state}`),
      ].join('\n')
    }
    const status: MapNodeData['status'] = isSubnet ? 'subnet' : (node.management_status ?? 'manual')
    const data: MapNodeData = {
      id: node.id,
      label: node.label,
      display,
      tooltip,
      kind: node.kind,
      deviceType: deviceType(node),
      role: node.role ?? 'unknown',
      status,
      tier: isSubnet ? -1 : tierOf(node),
      mgmtIp: node.mgmt_ip ?? '',
      model: node.model ?? '',
      gateways: gateways.join(', '),
      management: isSubnet && (node.management_subnet ?? false),
      anchor,
    }
    const classes = [
      data.kind,
      `type-${data.deviceType}`,
      `status-${data.status}`,
      data.management ? 'management' : '',
    ]
    return { data, classes: classes.filter(Boolean).join(' ') }
  })

  return {
    nodes,
    edges: edges.map((edge) => {
      const members = edge.members.length
      const activeMembers = edge.members.filter((member) => member.is_active).length
      const etherchannel = edge.kind === 'etherchannel'
      const ports =
        edge.kind === 'subnet_member'
          ? `${edge.source_interface ? shortPort(edge.source_interface.name) : ''} ${edge.address ?? ''}`.trim()
          : `${shortPort(edge.source_interface?.name)} ↔ ${shortPort(edge.target_interface?.name)}`
      const badge = !etherchannel
        ? ''
        : activeMembers === members
          ? `×${members}`
          : `${activeMembers}/${members}`
      const details = etherchannel
        ? edge.members
            .map(
              (member) =>
                `${shortPort(member.source_interface.name)} ↔ ${shortPort(member.target_interface.name)}${member.is_active ? '' : ' (–)'}`,
            )
            .join(', ')
        : edge.hsrp_state
          ? `HSRP ${edge.hsrp_state}`
          : ''
      const classes: string[] = [edge.kind]
      if (etherchannel && activeMembers < members) classes.push('degraded')
      if (edge.hsrp_state === 'active') classes.push('hsrp-active')
      else if (edge.hsrp_state) classes.push('hsrp-standby')
      return {
        data: {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          kind: edge.kind,
          badge,
          ports,
          tooltip: [ports, details].filter(Boolean).join(' · '),
          members,
          activeMembers,
        },
        classes: classes.join(' '),
      }
    }),
  }
}

/** Second caption line with the (translated, short) status of devices not managed. */
export function withStatusCaptions(
  elements: MapElements,
  describe: (status: ManagementStatus) => string,
): MapElements {
  return {
    edges: elements.edges,
    nodes: elements.nodes.map((node) => {
      const { status } = node.data
      if (status === 'subnet' || status === 'managed' || status === 'manual') return node
      return {
        ...node,
        data: { ...node.data, display: `${node.data.label}\n(${describe(status)})` },
      }
    }),
  }
}

/** The graph without management subnets (and their memberships). */
export function withoutManagementSubnets(elements: MapElements): MapElements {
  const hidden = new Set(elements.nodes.filter((n) => n.data.management).map((n) => n.data.id))
  return {
    nodes: elements.nodes.filter((node) => !hidden.has(node.data.id)),
    edges: elements.edges.filter(
      (edge) => !hidden.has(edge.data.source) && !hidden.has(edge.data.target),
    ),
  }
}

/** Row gap, and the smallest and largest gap between neighbours in a row. */
export const SPACING = { y: 120, minX: 140, maxX: 360 }

/**
 * Rows by tier, top to bottom. Each node sits under the average position of its neighbours
 * in the rows above (a subnet under its active HSRP gateway), then neighbours in a row are
 * pushed apart to at least the column gap (see spread). The column gap follows the canvas's aspect
 * ratio, so the graph fills a wide canvas instead of a narrow column in its middle.
 *
 * Subnets (L3) sit between the rows of their members, or below them: user subnets first,
 * management subnets in a row of their own.
 */
export function layoutByRole(elements: MapElements, aspect = 2): Record<string, Position> {
  const neighbours = new Map<string, string[]>()
  for (const { data } of elements.edges) {
    neighbours.set(data.source, [...(neighbours.get(data.source) ?? []), data.target])
    neighbours.set(data.target, [...(neighbours.get(data.target) ?? []), data.source])
  }
  const tier = new Map<string, number>()
  for (const { data } of elements.nodes) {
    if (data.kind === 'device') tier.set(data.id, data.tier)
  }
  for (const { data } of elements.nodes) {
    if (data.kind !== 'subnet') continue
    const memberTiers = (neighbours.get(data.id) ?? [])
      .map((id) => tier.get(id))
      .filter((value): value is number => value !== undefined)
    const low = Math.min(...memberTiers, TIER.core)
    const high = Math.max(...memberTiers, TIER.core)
    const anchorTier = data.anchor ? tier.get(data.anchor) : undefined
    const below = (anchorTier ?? high) + 1.4 + (data.management ? 1 : 0)
    tier.set(data.id, low === high || anchorTier !== undefined ? below : (low + high) / 2)
  }

  const rows = new Map<number, string[]>()
  for (const [id, rank] of tier) rows.set(rank, [...(rows.get(rank) ?? []), id])
  const ranks = [...rows.keys()].sort((a, b) => a - b)
  const widest = Math.max(1, ...[...rows.values()].map((row) => row.length))
  const height = Math.max(1, ranks.length - 1) * SPACING.y
  const gap =
    widest > 1
      ? Math.min(SPACING.maxX, Math.max(SPACING.minX, (aspect * height) / (widest - 1)))
      : SPACING.minX

  const nodeData = new Map(elements.nodes.map(({ data }) => [data.id, data]))
  const positions: Record<string, Position> = {}
  // Rows are evenly spaced by order: empty tiers take no room, rows between tiers (a
  // point-to-point subnet between a router and a core) get a full row of their own.
  ranks.forEach((rank, rowIndex) => {
    const row = rows.get(rank) ?? []
    const desired = (id: string): number | undefined => {
      const anchor = nodeData.get(id)?.anchor
      const anchored = anchor ? positions[anchor] : undefined
      if (anchored) return anchored.x
      const placed = (neighbours.get(id) ?? [])
        .map((other) => positions[other]?.x)
        .filter((x): x is number => x !== undefined)
      return placed.length > 0 ? placed.reduce((sum, x) => sum + x, 0) / placed.length : undefined
    }
    const label = (id: string) => nodeData.get(id)?.label ?? ''
    const wanted = new Map(row.map((id) => [id, desired(id)]))
    // Nodes with something above to follow, in that order; the others after them.
    const following = row.filter((id) => wanted.get(id) !== undefined)
    const free = row
      .filter((id) => wanted.get(id) === undefined)
      .sort((a, b) => label(a).localeCompare(label(b)))
    following.sort(
      (a, b) => (wanted.get(a) ?? 0) - (wanted.get(b) ?? 0) || label(a).localeCompare(label(b)),
    )
    row.splice(0, row.length, ...following, ...free)
    const last = following.length > 0 ? (wanted.get(following.at(-1) ?? '') ?? 0) : null
    const xs = spread(
      row.map(
        (id, index) =>
          wanted.get(id) ??
          (last === null
            ? (index - (row.length - 1) / 2) * gap
            : last + (index - following.length + 1) * gap),
      ),
      gap,
    )
    row.forEach((id, index) => {
      positions[id] = { x: xs[index] ?? 0, y: rowIndex * SPACING.y }
    })
  })
  return positions
}

/**
 * Positions as close as possible to ``desired`` (sorted) with at least ``gap`` between
 * neighbours: nodes wanting the same spot are centred on it as a group, then overlaps are
 * pushed apart to the right and to the left, and the two results averaged (both keep the
 * gap, so their average does too, and neither side drifts).
 */
export function spread(desired: number[], gap: number): number[] {
  const centred = [...desired]
  for (let start = 0; start < desired.length;) {
    let end = start
    while (end + 1 < desired.length && desired[end + 1] === desired[start]) end++
    for (let i = start; i <= end; i++) {
      centred[i] = (desired[start] ?? 0) + (i - start - (end - start) / 2) * gap
    }
    start = end + 1
  }
  const right = [...centred]
  for (let i = 1; i < right.length; i++)
    right[i] = Math.max(right[i] ?? 0, (right[i - 1] ?? 0) + gap)
  const left = [...centred]
  for (let i = left.length - 2; i >= 0; i--)
    left[i] = Math.min(left[i] ?? 0, (left[i + 1] ?? 0) - gap)
  return right.map((x, i) => (x + (left[i] ?? x)) / 2)
}

/** Saved positions where there are some, automatic ones for every other node. */
export function mergePositions(
  automatic: Record<string, Position>,
  saved: { node_id: string; x: number; y: number }[],
): Record<string, Position> {
  const merged = { ...automatic }
  for (const position of saved) {
    if (position.node_id in merged) merged[position.node_id] = { x: position.x, y: position.y }
  }
  return merged
}
