/**
 * Cytoscape stylesheet. Device type sets the shape, management status the border (style,
 * colour and width) and the second label line, so status never depends on colour alone.
 */
import type cytoscape from 'cytoscape'

interface Palette {
  text: string
  textBackground: string
  node: string
  border: string
  edge: string
  etherchannel: string
  subnet: string
  subnetBorder: string
  member: string
  hsrp: string
  selected: string
  unmanaged: string
  red: string
  orange: string
  grape: string
}

const LIGHT: Palette = {
  text: '#1a1b1e',
  textBackground: '#ffffff',
  node: '#e7f5ff',
  border: '#364fc7',
  edge: '#868e96',
  etherchannel: '#4263eb',
  subnet: '#f1f3f5',
  subnetBorder: '#495057',
  member: '#adb5bd',
  hsrp: '#0ca678',
  selected: '#f08c00',
  unmanaged: '#e9ecef',
  red: '#e03131',
  orange: '#e8590c',
  grape: '#9c36b5',
}

const DARK: Palette = {
  text: '#e9ecef',
  textBackground: '#1a1b1e',
  node: '#1c2a3a',
  border: '#748ffc',
  edge: '#909296',
  etherchannel: '#748ffc',
  subnet: '#25262b',
  subnetBorder: '#c1c2c5',
  member: '#5c5f66',
  hsrp: '#38d9a9',
  selected: '#ffa94d',
  unmanaged: '#2c2e33',
  red: '#ff6b6b',
  orange: '#ff922b',
  grape: '#da77f2',
}

export function stylesheet(scheme: 'light' | 'dark'): cytoscape.StylesheetJson {
  const c = scheme === 'dark' ? DARK : LIGHT
  return [
    {
      selector: 'node',
      style: {
        label: 'data(display)',
        'text-wrap': 'wrap',
        'text-valign': 'bottom',
        'text-margin-y': 5,
        'font-size': 14,
        'min-zoomed-font-size': 6,
        color: c.text,
        'text-background-color': c.textBackground,
        'text-background-opacity': 0.75,
        'text-background-padding': '2px',
        'background-color': c.node,
        'border-color': c.border,
        'border-width': 2,
        width: 46,
        height: 30,
        shape: 'round-rectangle',
      },
    },
    { selector: 'node.type-router', style: { shape: 'diamond', width: 44, height: 44 } },
    { selector: 'node.type-l3_switch', style: { width: 58, height: 40, 'border-width': 3 } },
    { selector: 'node.type-switch', style: { width: 54, height: 26 } },
    { selector: 'node.type-ap', style: { shape: 'triangle', width: 34, height: 30 } },
    {
      selector: 'node.type-unknown, node.type-firewall, node.type-wlc',
      style: { shape: 'hexagon', width: 38, height: 34 },
    },
    {
      selector: 'node.subnet',
      style: {
        shape: 'round-tag',
        width: 30,
        height: 22,
        'background-color': c.subnet,
        'border-color': c.subnetBorder,
        'border-width': 1,
        'border-style': 'solid',
        'font-size': 12,
      },
    },
    { selector: 'node.unmanaged', style: { 'background-color': c.unmanaged } },
    {
      selector: 'node.status-out_of_scope',
      style: { 'border-style': 'dashed', 'border-color': c.edge, opacity: 0.6 },
    },
    {
      selector: 'node.status-auth_failed',
      style: { 'border-style': 'double', 'border-color': c.red, 'border-width': 6 },
    },
    {
      selector: 'node.status-unreachable',
      style: { 'border-style': 'dashed', 'border-color': c.orange, 'border-width': 3 },
    },
    {
      selector: 'node.status-unsupported_platform',
      style: { 'border-style': 'dotted', 'border-color': c.grape, 'border-width': 3 },
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
        'font-size': 11,
        color: c.text,
        'text-rotation': 'autorotate',
        'text-background-color': c.textBackground,
        'text-background-opacity': 0.85,
        'text-background-padding': '2px',
      },
    },
    {
      selector: 'edge.etherchannel',
      style: { width: 7, 'line-color': c.etherchannel, 'font-weight': 'bold' },
    },
    { selector: 'edge.degraded', style: { 'line-style': 'dashed' } },
    { selector: 'edge.subnet_member', style: { width: 1.5, 'line-color': c.member } },
    { selector: 'edge.hsrp-active', style: { width: 3, 'line-color': c.hsrp } },
    {
      selector: 'edge.hover',
      style: { label: 'data(hoverLabel)', 'font-size': 11, 'z-index': 10 },
    },
  ]
}
