import React, { useMemo } from 'react'
import ReactFlow, { Background, Controls, MiniMap } from 'reactflow'
import 'reactflow/dist/style.css'
import { layoutGraph } from '../utils/layout'

export default function GraphView({ rawNodes, rawEdges, highlightedIds = [], onNodeClick }) {
  const { nodes, edges } = useMemo(() => layoutGraph(rawNodes, rawEdges), [rawNodes, rawEdges])

  const styledNodes = nodes.map((n) => ({
    ...n,
    style: {
      ...n.style,
      boxShadow: highlightedIds.includes(n.id) ? '0 0 0 2px #4fa8a0' : 'none',
    },
  }))

  const styledEdges = edges.map((e) => {
    const isHighlighted = highlightedIds.includes(e.source) && highlightedIds.includes(e.target)
    return {
      ...e,
      style: {
        stroke: isHighlighted ? '#4fa8a0' : '#3a3f4a',
        strokeWidth: isHighlighted ? 2.5 : 1.5,
      },
    }
  })

  return (
    <ReactFlow
      nodes={styledNodes}
      edges={styledEdges}
      onNodeClick={(_, node) => onNodeClick(node.data.raw)}
      fitView
      proOptions={{ hideAttribution: true }}
    >
      <Background color="#2a2e37" gap={20} />
      <Controls />
      <MiniMap nodeColor={() => '#c98a3e'} maskColor="rgba(20,22,26,0.85)" style={{ background: '#1c1f26' }} />
    </ReactFlow>
  )
}
