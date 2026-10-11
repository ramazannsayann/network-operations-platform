/**
 * Node icons for the map: generic Tabler icons (the project's icon set), as SVG data URIs
 * that Cytoscape draws inside the node shapes. No vendor artwork.
 */
import accessPoint from '@tabler/icons/outline/access-point.svg?raw'
import antenna from '@tabler/icons/outline/antenna.svg?raw'
import helpHexagon from '@tabler/icons/outline/help-hexagon.svg?raw'
import network from '@tabler/icons/outline/network.svg?raw'
import router from '@tabler/icons/outline/router.svg?raw'
import server2 from '@tabler/icons/outline/server-2.svg?raw'
import stack3 from '@tabler/icons/outline/stack-3.svg?raw'
import wall from '@tabler/icons/outline/wall.svg?raw'
import {
  IconAccessPoint,
  IconAntenna,
  IconHelpHexagon,
  IconNetwork,
  IconRouter,
  IconServer2,
  IconStack3,
  IconWall,
  type Icon,
} from '@tabler/icons-react'

/** Icon per map node type (device_type, or "subnet"), for the legend and the side panel. */
export const NODE_ICONS: Record<string, Icon> = {
  router: IconRouter,
  l3_switch: IconStack3,
  switch: IconServer2,
  ap: IconAccessPoint,
  firewall: IconWall,
  wlc: IconAntenna,
  unknown: IconHelpHexagon,
  subnet: IconNetwork,
}

/** The same icons as SVG source, for the canvas. */
const SVG: Record<string, string> = {
  router,
  l3_switch: stack3,
  switch: server2,
  ap: accessPoint,
  firewall: wall,
  wlc: antenna,
  unknown: helpHexagon,
  subnet: network,
}

/** ``data:image/svg+xml`` of a node type's icon drawn in ``color``. */
export function iconDataUri(type: string, color: string): string {
  const svg = (SVG[type] ?? helpHexagon)
    .replaceAll('currentColor', color)
    .replace('stroke-width="2"', 'stroke-width="1.75"')
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}
