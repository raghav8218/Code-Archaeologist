import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCollide,
  forceX,
  forceY,
} from 'd3-force'
import { MarkerType } from 'reactflow'

export const NODE_CONFIG = {
  class: {
    radius: 26,
    color: '#8B5CF6',
    border: '#A78BFA',
    label: 'Class',
    icon: 'C',
  },
  route: {
    radius: 20,
    color: '#F43F5E',
    border: '#FB7185',
    label: 'Route',
    icon: '⇄',
  },
  function: {
    radius: 16,
    color: '#06B6D4',
    border: '#22D3EE',
    label: 'Function',
    icon: 'ƒ',
  },
  method: {
    radius: 16,
    color: '#10B981',
    border: '#34D399',
    label: 'Method',
    icon: 'm',
  },
  external: {
    radius: 12,
    color: '#F59E0B',
    border: '#FBBF24',
    label: 'Utility',
    icon: '✦',
  },
}

// Deterministic jitter based on string hash
function pseudoRandom(seed) {
  let h = 0
  for (let i = 0; i < seed.length; i++) {
    h = Math.imul(31, h) + seed.charCodeAt(i) | 0
  }
  return ((h % 1000) / 1000) - 0.5
}

export function layoutGraph(rawNodes = [], rawEdges = []) {
  if (!rawNodes.length) {
    return { nodes: [], edges: [], fileHulls: [] }
  }

  // Group nodes by file to establish initial cluster positions
  const files = [...new Set(rawNodes.map((n) => n.file || 'misc'))]
  const clusterCenters = {}

  // Arrange file cluster centers with ample breathing room so hulls don't collide
  const cols = Math.max(1, Math.ceil(Math.sqrt(files.length * 1.5)))
  const spacingX = 580
  const spacingY = 480

  files.forEach((file, index) => {
    const col = index % cols
    const row = Math.floor(index / cols)
    clusterCenters[file] = {
      x: (col - cols / 2) * spacingX,
      y: (row - Math.ceil(files.length / cols) / 2) * spacingY,
    }
  })

  // Prepare nodes for d3-force simulation
  const simulationNodes = rawNodes.map((n) => {
    const kind = n.kind || (n.is_route ? 'route' : 'function')
    const config = NODE_CONFIG[kind] || NODE_CONFIG.function
    const center = clusterCenters[n.file || 'misc'] || { x: 0, y: 0 }

    const jitterX = pseudoRandom(n.id + '_x') * 160
    const jitterY = pseudoRandom(n.id + '_y') * 160

    return {
      id: n.id,
      raw: n,
      kind,
      radius: config.radius,
      file: n.file || 'misc',
      x: center.x + jitterX,
      y: center.y + jitterY,
    }
  })

  const nodeMap = new Map(simulationNodes.map((n) => [n.id, n]))

  // Filter edges to only those whose source and target exist
  const simulationLinks = rawEdges
    .filter((e) => nodeMap.has(e.source) && nodeMap.has(e.target))
    .map((e) => ({
      source: e.source,
      target: e.target,
      type: e.type || 'calls',
      weight: e.weight || 1,
    }))

  // Create d3-force simulation with generous collision radius
  const simulation = forceSimulation(simulationNodes)
    .force(
      'link',
      forceLink(simulationLinks)
        .id((d) => d.id)
        .distance((d) => (d.type === 'contains' ? 65 : 140))
        .strength((d) => (d.type === 'contains' ? 0.7 : 0.2))
    )
    .force('charge', forceManyBody().strength(-220))
    // Generous collision prevention padding
    .force(
      'collide',
      forceCollide()
        .radius((d) => d.radius + 48)
        .iterations(4)
    )
    .force(
      'x',
      forceX((d) => clusterCenters[d.file]?.x || 0).strength(0.32)
    )
    .force(
      'y',
      forceY((d) => clusterCenters[d.file]?.y || 0).strength(0.32)
    )
    .stop()

  // Run simulation synchronously
  simulation.tick(250)

  // Compute file clusters (bounding boxes for translucent hulls)
  const fileBounds = {}
  simulationNodes.forEach((node) => {
    const f = node.file
    if (!fileBounds[f]) {
      fileBounds[f] = {
        minX: Infinity,
        maxX: -Infinity,
        minY: Infinity,
        maxY: -Infinity,
        count: 0,
        file: f,
      }
    }
    const r = node.radius
    fileBounds[f].minX = Math.min(fileBounds[f].minX, node.x - r)
    fileBounds[f].maxX = Math.max(fileBounds[f].maxX, node.x + r)
    fileBounds[f].minY = Math.min(fileBounds[f].minY, node.y - r)
    fileBounds[f].maxY = Math.max(fileBounds[f].maxY, node.y + r)
    fileBounds[f].count += 1
  })

  const padding = 38
  const headerHeight = 38

  // Generate file hull background nodes
  const hullNodes = Object.entries(fileBounds)
    .filter(([file]) => file !== 'external' && file !== 'misc')
    .map(([file, b]) => {
      const width = Math.max(160, b.maxX - b.minX + padding * 2)
      const height = Math.max(100, b.maxY - b.minY + padding * 2 + headerHeight)
      return {
        id: `hull_${file}`,
        type: 'fileHull',
        position: {
          x: b.minX - padding,
          y: b.minY - padding - headerHeight,
        },
        data: {
          file,
          symbolCount: b.count,
          width,
          height,
        },
        style: {
          width,
          height,
          zIndex: -1,
        },
        selectable: false,
        draggable: false,
      }
    })

  // Format ReactFlow circular nodes (fully draggable!)
  const reactFlowNodes = simulationNodes.map((n) => {
    const config = NODE_CONFIG[n.kind] || NODE_CONFIG.function
    return {
      id: n.id,
      type: 'circularNode',
      draggable: true,
      position: {
        x: n.x - config.radius,
        y: n.y - config.radius,
      },
      data: {
        id: n.id,
        raw: n.raw,
        label: n.raw.label || n.raw.name,
        name: n.raw.name,
        qualified_name: n.raw.qualified_name || n.raw.name,
        kind: n.kind,
        file: n.file,
        radius: config.radius,
        color: config.color,
        border: config.border,
        icon: config.icon,
        change_frequency: n.raw.change_frequency || 0,
        loc: n.raw.loc || 0,
        complexity: n.raw.complexity || 1,
      },
      zIndex: 10,
    }
  })

  const allNodes = [...hullNodes, ...reactFlowNodes]

  // Format edges: directional curved cubic-bezier links
  const edges = simulationLinks.map((e, index) => {
    const sourceId = typeof e.source === 'object' && e.source !== null ? e.source.id : e.source
    const targetId = typeof e.target === 'object' && e.target !== null ? e.target.id : e.target
    const edgeType = e.type || 'calls'

    let stroke = '#64748B' // Subtle default slate stroke
    let strokeDasharray = undefined

    if (edgeType === 'contains') {
      stroke = '#8B5CF6'
      strokeDasharray = '3 3'
    } else if (edgeType === 'imports') {
      stroke = '#C084FC'
      strokeDasharray = '5 4'
    } else if (edgeType === 'instantiates') {
      stroke = '#818CF8'
    } else if (edgeType === 'calls') {
      stroke = '#38BDF8'
    }

    return {
      id: `e-${index}-${sourceId}-${targetId}`,
      source: sourceId,
      target: targetId,
      // Curved cubic-bezier links
      type: 'default',
      animated: false,
      style: {
        stroke,
        strokeWidth: 1.3,
        opacity: 0.22, // Subtle by default to avoid hairball
        strokeDasharray,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: stroke,
        width: 12,
        height: 12,
      },
      data: {
        edgeType,
        weight: e.weight,
        sourceId,
        targetId,
        baseStroke: stroke,
        baseStrokeDasharray: strokeDasharray,
      },
    }
  })

  return { nodes: allNodes, edges }
}
