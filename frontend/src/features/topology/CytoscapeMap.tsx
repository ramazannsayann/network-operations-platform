import { Paper, Text } from '@mantine/core'
import cytoscape from 'cytoscape'
import { type Ref, useEffect, useImperativeHandle, useRef, useState } from 'react'

import type { MapElements, Position } from './elements'
import { stylesheet } from './style'

/** What the page can ask of the map. */
export interface MapController {
  /** Current node positions (after any dragging). */
  positions(): { node_id: string; x: number; y: number }[]
  focus(id: string): void
  fit(): void
}

interface Props {
  elements: MapElements
  positions: Record<string, Position>
  scheme: 'light' | 'dark'
  selected: string | null
  onSelect: (id: string | null) => void
  label: string
  ref?: Ref<MapController>
}

const PADDING = 48
// Small graphs would otherwise be blown up to fill the canvas.
const MAX_FIT_ZOOM = 1.5

function fit(instance: cytoscape.Core) {
  instance.fit(undefined, PADDING)
  if (instance.zoom() > MAX_FIT_ZOOM) {
    instance.zoom(MAX_FIT_ZOOM)
    instance.center()
  }
}

interface Tooltip {
  x: number
  y: number
  text: string
}

export function CytoscapeMap({
  elements,
  positions,
  scheme,
  selected,
  onSelect,
  label,
  ref,
}: Props) {
  const wrapper = useRef<HTMLDivElement>(null)
  const container = useRef<HTMLDivElement>(null)
  const cy = useRef<cytoscape.Core | null>(null)
  const [tooltip, setTooltip] = useState<Tooltip | null>(null)
  const onSelectRef = useRef(onSelect)
  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  const canvasColor = () =>
    (wrapper.current && getComputedStyle(wrapper.current).backgroundColor) || '#ffffff'

  useEffect(() => {
    const instance = cytoscape({
      container: container.current,
      style: stylesheet(scheme, canvasColor()),
      layout: { name: 'preset' },
      minZoom: 0.15,
      maxZoom: 3,
      boxSelectionEnabled: false,
    })
    instance.on('tap', 'node', (event: cytoscape.EventObjectNode) => {
      onSelectRef.current(event.target.id())
    })
    instance.on('tap', (event) => {
      if (event.target === instance) onSelectRef.current(null)
    })
    const show = (event: cytoscape.EventObjectNode | cytoscape.EventObjectEdge) => {
      const text = event.target.data('tooltip') as string
      if (event.target.isEdge()) event.target.addClass('hover')
      if (text) setTooltip({ x: event.renderedPosition.x, y: event.renderedPosition.y, text })
    }
    const hide = (event: cytoscape.EventObjectNode | cytoscape.EventObjectEdge) => {
      event.target.removeClass('hover')
      setTooltip(null)
    }
    instance.on('mouseover', 'node, edge', show)
    instance.on('mouseout', 'node, edge', hide)
    instance.on('viewport drag', () => {
      setTooltip(null)
    })
    cy.current = instance
    // Cytoscape measures its container once; follow later size changes (side panel).
    const observer = new ResizeObserver(() => {
      instance.resize()
    })
    if (container.current) observer.observe(container.current)
    return () => {
      observer.disconnect()
      instance.destroy()
      cy.current = null
    }
    // The instance lives as long as the component; data and style are applied below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const instance = cy.current
    if (!instance) return
    instance.batch(() => {
      instance.elements().remove()
      instance.add([
        ...elements.nodes.map((node) => ({
          group: 'nodes' as const,
          data: node.data,
          classes: node.classes,
          position: positions[node.data.id] ?? { x: 0, y: 0 },
        })),
        ...elements.edges.map((edge) => ({
          group: 'edges' as const,
          data: edge.data,
          classes: edge.classes,
        })),
      ])
    })
    instance.resize()
    fit(instance)
    setTooltip(null)
  }, [elements, positions])

  useEffect(() => {
    cy.current?.style(stylesheet(scheme, canvasColor()))
  }, [scheme])

  useEffect(() => {
    const instance = cy.current
    if (!instance) return
    instance.$(':selected').unselect()
    if (selected) instance.$id(selected).select()
  }, [selected, elements])

  useImperativeHandle(
    ref,
    () => ({
      positions: () =>
        (cy.current?.nodes() ?? []).map((node) => ({
          node_id: node.id(),
          x: Math.round(node.position('x') * 10) / 10,
          y: Math.round(node.position('y') * 10) / 10,
        })),
      focus: (id: string) => {
        const node = cy.current?.$id(id)
        if (node && node.nonempty()) {
          cy.current?.animate({ center: { eles: node }, zoom: 1.4 }, { duration: 300 })
        }
      },
      fit: () => {
        if (cy.current) fit(cy.current)
      },
    }),
    [],
  )

  return (
    <div
      ref={wrapper}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: 420,
        background: 'var(--mantine-color-body)',
      }}
    >
      <div
        ref={container}
        role="img"
        aria-label={label}
        data-testid="topology-map"
        style={{ position: 'absolute', inset: 0 }}
      />
      {tooltip && (
        <Paper
          shadow="md"
          withBorder
          px="xs"
          py={4}
          role="tooltip"
          style={{
            position: 'absolute',
            left: tooltip.x + 14,
            top: tooltip.y + 14,
            pointerEvents: 'none',
            zIndex: 5,
            maxWidth: 360,
          }}
        >
          <Text size="xs" className="mono" style={{ whiteSpace: 'pre-line' }}>
            {tooltip.text}
          </Text>
        </Paper>
      )}
    </div>
  )
}
