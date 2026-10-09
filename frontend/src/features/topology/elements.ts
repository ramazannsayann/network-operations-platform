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

/** Data carried by a Cytoscape node; read by the stylesheet and the side panel. */
export interface MapNodeData {
  id: string
  label: string
  /** The node's caption on the map: the label, plus the status for unmanaged nodes. */
  display: string
  kind: 'device' | 'subnet'
  deviceType: string
  role: string
  status: ManagementStatus | 'subnet'
  tier: number
  mgmtIp: string
  model: string
  gateways: string
}

export interface MapEdgeData {
  id: string
  source: string
  target: string
  kind: TopologyEdge['kind']
  /** Shown on the edge: member count of an EtherChannel, the HSRP state on L3. */
  badge: string
  /** Local and remote ports. */
  ports: string
  /** Shown on hover: the ports and the badge. */
  hoverLabel: string
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

function nodeData(node: TopologyNode): MapNodeData {
  const isSubnet = node.kind === 'subnet'
  return {
    id: node.id,
    label: node.label,
    display: node.label,
    kind: node.kind,
    deviceType: node.device_type ?? (isSubnet ? 'subnet' : 'unknown'),
    role: node.role ?? 'unknown',
    status: isSubnet ? 'subnet' : (node.management_status ?? 'manual'),
    tier: isSubnet ? -1 : tierOf(node),
    mgmtIp: node.mgmt_ip ?? '',
    model: node.model ?? '',
    gateways: (node.gateway_ips ?? []).join(', '),
  }
}

function edgeData(edge: TopologyEdge): MapEdgeData {
  const members = edge.members.length
  const activeMembers = edge.members.filter((member) => member.is_active).length
  let badge = ''
  if (edge.kind === 'etherchannel') {
    badge = activeMembers === members ? `×${members}` : `${activeMembers}/${members}`
  } else if (edge.kind === 'subnet_member' && edge.hsrp_state === 'active') {
    badge = 'HSRP active' // the router answering for the gateway; others show on hover
  }
  const ports =
    edge.kind === 'subnet_member'
      ? `${shortPort(edge.source_interface?.name ?? '')} ${edge.address ?? ''}`.trim()
      : `${shortPort(edge.source_interface?.name)} ↔ ${shortPort(edge.target_interface?.name)}`
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    kind: edge.kind,
    badge,
    ports,
    hoverLabel: [ports, badge || (edge.hsrp_state ? `HSRP ${edge.hsrp_state}` : '')]
      .filter(Boolean)
      .join(' · '),
    members,
    activeMembers,
  }
}

export function toElements(topology: Topology): MapElements {
  const ids = new Set(topology.nodes.map((node) => node.id))
  const nodes = topology.nodes.map((node) => {
    const data = nodeData(node)
    const classes = [
      data.kind,
      `type-${data.deviceType}`,
      `status-${data.status}`,
      data.status !== 'managed' && data.status !== 'subnet' && data.status !== 'manual'
        ? 'unmanaged'
        : '',
    ]
    return { data, classes: classes.filter(Boolean).join(' ') }
  })
  const edges = topology.edges
    .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
    .map((edge) => {
      const data = edgeData(edge)
      const classes: string[] = [data.kind]
      if (data.kind === 'etherchannel' && data.activeMembers < data.members)
        classes.push('degraded')
      if (edge.hsrp_state === 'active') classes.push('hsrp-active')
      return { data, classes: classes.join(' ') }
    })
  return { nodes, edges }
}

/** Second caption line with the (translated) status of nodes the platform does not manage. */
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

export const SPACING = { x: 150, y: 105 }

/**
 * Rows by tier, top to bottom; within a row, nodes follow the average position of their
 * neighbours in the rows above (fewer crossings), then their label. Subnets (L3) sit
 * between the rows of their members.
 */
export function layoutByRole(elements: MapElements): Record<string, Position> {
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
    // Between its members, or just below them when they are all on one row.
    tier.set(data.id, low === high ? high + 1.5 : (low + high) / 2)
  }

  const rows = new Map<number, string[]>()
  const labels = new Map(elements.nodes.map(({ data }) => [data.id, data.label]))
  for (const [id, rank] of tier) rows.set(rank, [...(rows.get(rank) ?? []), id])

  const positions: Record<string, Position> = {}
  for (const rank of [...rows.keys()].sort((a, b) => a - b)) {
    const row = rows.get(rank) ?? []
    const weight = (id: string): number => {
      const placed = (neighbours.get(id) ?? [])
        .map((other) => positions[other]?.x)
        .filter((x): x is number => x !== undefined)
      return placed.length > 0 ? placed.reduce((sum, x) => sum + x, 0) / placed.length : 0
    }
    row.sort(
      (a, b) => weight(a) - weight(b) || (labels.get(a) ?? '').localeCompare(labels.get(b) ?? ''),
    )
    row.forEach((id, index) => {
      positions[id] = {
        x: (index - (row.length - 1) / 2) * SPACING.x,
        y: rank * SPACING.y,
      }
    })
  }
  return positions
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
