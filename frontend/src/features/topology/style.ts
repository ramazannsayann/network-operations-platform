/**
 * Cytoscape stylesheet. Device type sets the shape and the icon, management status the
 * border (style, colour, width) and the second caption line, so status never depends on
 * colour alone. Warning colours are kept for real problems (auth_failed, unreachable).
 */
import type cytoscape from 'cytoscape'

import { iconDataUri } from './icons'

interface Palette {
  text: string
  node: string
  border: string
  icon: string
  edge: string
  etherchannel: string
  subnet: string
  subnetBorder: string
  member: string
  hsrp: string
  selected: string
  muted: string
  red: string
  orange: string
}

const LIGHT: Palette = {
  text: '#1a1b1e',
  node: '#edf2ff',
  border: '#3b5bdb',
  icon: '#364fc7',
  edge: '#868e96',
  etherchannel: '#4263eb',
  subnet: '#f8f9fa',
  subnetBorder: '#868e96',
  member: '#ced4da',
  hsrp: '#0ca678',
  selected: '#f08c00',
  muted: '#adb5bd',
  red: '#e03131',
  orange: '#e8590c',
}

const DARK: Palette = {
  text: '#e9ecef',
  node: '#1f2b47',
  border: '#748ffc',
  icon: '#91a7ff',
  edge: '#909296',
  etherchannel: '#748ffc',
  subnet: '#2c2e33',
  subnetBorder: '#909296',
  member: '#4a4d54',
  hsrp: '#38d9a9',
  selected: '#ffa94d',
  muted: '#5c5f66',
  red: '#ff6b6b',
  orange: '#ff922b',
}

/** Shape and size per node type; distinct shapes, the icon inside names the type. */
const SHAPES: Record<string, { shape: string; width: number; height: number }> = {
  router: { shape: 'ellipse', width: 58, height: 58 },
  l3_switch: { shape: 'round-rectangle', width: 76, height: 52 },
  switch: { shape: 'rectangle', width: 68, height: 40 },
  ap: { shape: 'round-triangle', width: 54, height: 50 },
  firewall: { shape: 'round-hexagon', width: 60, height: 54 },
  wlc: { shape: 'round-octagon', width: 56, height: 56 },
  unknown: { shape: 'round-diamond', width: 54, height: 54 },
  subnet: { shape: 'round-tag', width: 46, height: 34 },
}

/**
 * @param canvas the map's background colour: captions sit on it, so edges never run
 *   through their text.
 */
export function stylesheet(scheme: 'light' | 'dark', canvas: string): cytoscape.StylesheetJson {
  const c = scheme === 'dark' ? DARK : LIGHT
  const types: cytoscape.StylesheetJson = Object.entries(SHAPES).map(([type, look]) => ({
    selector: `node.type-${type}`,
    style: {
      shape: look.shape as cytoscape.Css.NodeShape,
      width: look.width,
      height: look.height,
      'background-image': iconDataUri(type, type === 'subnet' ? c.subnetBorder : c.icon),
    },
  }))
  return [
    {
      selector: 'node',
      style: {
        label: 'data(display)',
        'text-wrap': 'wrap',
        'text-max-width': '220px',
        'text-valign': 'bottom',
        'text-margin-y': 6,
        'font-size': 17,
        'font-weight': 500,
        color: c.text,
        'text-background-color': canvas,
        'text-background-opacity': 1,
        'text-background-padding': '3px',
        'text-background-shape': 'roundrectangle',
        'background-color': c.node,
        'background-width': '55%',
        'background-height': '55%',
        'background-fit': 'none',
        'background-clip': 'none',
        'border-color': c.border,
        'border-width': 2,
        'z-index': 10,
      },
    },
    ...types,
    { selector: 'node.type-l3_switch', style: { 'border-width': 3 } },
    {
      selector: 'node.subnet',
      style: {
        'background-color': c.subnet,
        'border-color': c.subnetBorder,
        'border-width': 1,
        'font-size': 15,
        'font-weight': 400,
      },
    },
    // Not managed, and that is a fact rather than a fault: neutral.
    {
      selector: 'node.status-out_of_scope',
      style: {
        'border-style': 'dashed',
        'border-color': c.muted,
        'background-color': canvas,
        opacity: 0.65,
      },
    },
    {
      selector: 'node.status-unsupported_platform',
      style: { 'border-color': c.muted, 'border-width': 1.5, 'background-color': canvas },
    },
    // Real problems: warning colours, plus a border style.
    {
      selector: 'node.status-auth_failed',
      style: { 'border-style': 'double', 'border-color': c.red, 'border-width': 6 },
    },
    {
      selector: 'node.status-unreachable',
      style: { 'border-style': 'dashed', 'border-color': c.orange, 'border-width': 3 },
    },
    {
      selector: 'node:selected',
      style: { 'overlay-color': c.selected, 'overlay-opacity': 0.25, 'overlay-padding': 8 },
    },
    {
      selector: 'edge',
      style: {
        width: 2,
        'line-color': c.edge,
        'curve-style': 'bezier',
        label: 'data(badge)',
        'font-size': 12,
        'font-weight': 'bold',
        color: c.text,
        'text-background-color': canvas,
        'text-background-opacity': 1,
        'text-background-padding': '2px',
        'z-index': 1,
      },
    },
    { selector: 'edge.etherchannel', style: { width: 8, 'line-color': c.etherchannel } },
    { selector: 'edge.degraded', style: { 'line-style': 'dashed' } },
    // L3: no text on edges; the style says it (explained in the legend).
    { selector: 'edge.subnet_member', style: { width: 1.5, 'line-color': c.member } },
    { selector: 'edge.hsrp-active', style: { width: 4, 'line-color': c.hsrp } },
    {
      selector: 'edge.hsrp-standby',
      style: { width: 2, 'line-color': c.hsrp, 'line-style': 'dashed' },
    },
    { selector: 'edge.hover', style: { 'underlay-color': c.selected, 'underlay-opacity': 0.3 } },
  ]
}
