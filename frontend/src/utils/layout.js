import dagre from 'dagre'

const NODE_WIDTH = 200
const NODE_HEIGHT = 56

export function layoutGraph(rawNodes, rawEdges) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 90 })
  g.setDefaultEdgeLabel(() => ({}))

  rawNodes.forEach((n) => g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }))
  rawEdges.forEach((e) => g.setEdge(e.source, e.target))

  dagre.layout(g)

  // Hotspot scale: nodes that changed more often in git history get a
  // visibly thicker, warmer border — the graph carries a history signal,
  // not just structure.
  const maxFreq = Math.max(1, ...rawNodes.map((n) => n.change_frequency || 0))

  const nodes = rawNodes.map((n) => {
    const pos = g.node(n.id)
    const freq = n.change_frequency || 0
    const label = freq > 0 ? `${n.qualified_name || n.name}\n↻ ${freq} commit${freq === 1 ? '' : 's'}` : (n.qualified_name || n.name)
    return {
      id: n.id,
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data: { label, raw: n },
      style: nodeStyle(n, maxFreq),
    }
  })

  const edges = rawEdges.map((e, i) => ({
    id: `e-${i}-${e.source}-${e.target}`,
    source: e.source,
    target: e.target,
    style: { stroke: '#3a3f4a', strokeWidth: 1.5 },
  }))

  return { nodes, edges }
}

function nodeStyle(n, maxFreq) {
  const isRoute = n.is_route
  const freq = n.change_frequency || 0
  const intensity = maxFreq > 0 ? freq / maxFreq : 0
  const borderWidth = 1 + Math.round(intensity * 3) // 1px (cold) to 4px (hotspot)
  const borderColor = isRoute ? '#c98a3e' : (intensity > 0.5 ? '#d9634a' : '#2a2e37')
  return {
    background: isRoute ? '#c98a3e' : '#1c1f26',
    color: isRoute ? '#14161a' : '#e8e6df',
    border: `${borderWidth}px solid ${borderColor}`,
    borderRadius: 6,
    fontFamily: '"IBM Plex Mono", monospace',
    fontSize: 11.5,
    padding: 8,
    width: NODE_WIDTH,
    whiteSpace: 'pre-line',
    lineHeight: 1.4,
  }
}
