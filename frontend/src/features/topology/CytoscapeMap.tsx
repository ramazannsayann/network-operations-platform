import cytoscape from 'cytoscape'
import { type Ref, useEffect, useImperativeHandle, useRef } from 'react'

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

export function CytoscapeMap({
  elements,
  positions,
  scheme,
  selected,
  onSelect,
  label,
  ref,
}: Props) {
  const container = useRef<HTMLDivElement>(null)
  const cy = useRef<cytoscape.Core | null>(null)
  const onSelectRef = useRef(onSelect)
  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  useEffect(() => {
    const instance = cytoscape({
      container: container.current,
      style: stylesheet(scheme),
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
    instance.on('mouseover', 'edge', (event: cytoscape.EventObjectEdge) => {
      event.target.addClass('hover')
    })
    instance.on('mouseout', 'edge', (event: cytoscape.EventObjectEdge) => {
      event.target.removeClass('hover')
    })
    cy.current = instance
    return () => {
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
    instance.fit(undefined, 40)
  }, [elements, positions])

  useEffect(() => {
    cy.current?.style(stylesheet(scheme))
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
        cy.current?.fit(undefined, 40)
      },
    }),
    [],
  )

  return (
    <div
      ref={container}
      role="img"
      aria-label={label}
      data-testid="topology-map"
      style={{ width: '100%', height: '100%', minHeight: 420 }}
    />
  )
}
