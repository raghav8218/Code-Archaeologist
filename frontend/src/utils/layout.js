import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCollide,
  forceX,
  forceY,
  forceCenter,
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

export function getModuleGroup(filePath) {
  if (!filePath || filePath === 'external' || filePath === 'misc') return 'external'
  const normalized = filePath.replace(/\\/g, '/')
  const parts = normalized.split('/')
  if (parts.length === 1) return parts[0]
  // Group by top-level directory or package (e.g. "pandas/core" or "src/auth")
  return parts.length >= 3 ? `${parts[0]}/${parts[1]}` : parts[0]
}

export function layoutGraph(rawNodes = [], rawEdges = []) {
  if (!rawNodes || !rawNodes.length) {
    return { nodes: [], edges: [], fileHulls: [] }
  }

  // 1. Group nodes by their parent architectural package/module
  const groupNodesMap = {}
  rawNodes.forEach((n) => {
    const group = getModuleGroup(n.file)
    groupNodesMap[group] = groupNodesMap[group] || []
    groupNodesMap[group].push(n)
  })

  const groups = Object.keys(groupNodesMap)
  const countClusters = groups.length

  // 2. Compute non-overlapping cluster centers dynamically based on group size
  const clusterMeta = groups.map((grp, i) => {
    const count = groupNodesMap[grp].length
    const radius = Math.max(180, Math.sqrt(count) * 60 + 60)
    const angle = (i * 2 * Math.PI) / countClusters
    const dist = countClusters > 1 ? 480 + (i % 2) * 60 : 0
    return {
      id: grp,
      radius,
      x: Math.cos(angle) * dist,
      y: Math.sin(angle) * dist,
    }
  })

  // Separate cluster centers with collision force to guarantee ZERO overlap
  const centerSim = forceSimulation(clusterMeta)
    .force('collide', forceCollide((d) => d.radius + 70).iterations(3))
    .force('center', forceCenter(0, 0))
    .stop()

  for (let i = 0; i < 35; ++i) centerSim.tick()

  const clusterCenters = {}
  clusterMeta.forEach((cm) => {
    clusterCenters[cm.id] = { x: cm.x, y: cm.y, radius: cm.radius }
  })

  // 3. Prepare nodes with organic positions around their module center
  const simulationNodes = rawNodes.map((n, idx) => {
    const kind = n.kind || (n.is_route ? 'route' : 'function')
    const config = NODE_CONFIG[kind] || NODE_CONFIG.function
    const group = getModuleGroup(n.file)
    const center = clusterCenters[group] || { x: 0, y: 0 }

    const isHub = n.is_keystone || kind === 'class' || kind === 'route'
    const angle = (idx * 137.5 * Math.PI) / 180
    const dist = isHub ? 20 + (idx % 3) * 20 : 55 + (idx % 6) * 32

    return {
      id: n.id,
      raw: n,
      kind,
      radius: config.radius,
      file: n.file || 'misc',
      group,
      x: center.x + Math.cos(angle) * dist,
      y: center.y + Math.sin(angle) * dist,
    }
  })

  // 4. Map valid links
  const nodeMap = new Map(simulationNodes.map((n) => [n.id, n]))
  const validEdges = (rawEdges || [])
    .filter((e) => nodeMap.has(e.source) && nodeMap.has(e.target))
    .map((e) => ({
      source: e.source,
      target: e.target,
      type: e.type || 'calls',
      weight: e.weight || 1,
    }))

  // 5. Fast, bounded force simulation (converges in ~12ms with distanceMax cutoff)
  const sim = forceSimulation(simulationNodes)
    .force(
      'link',
      forceLink(validEdges)
        .id((d) => d.id)
        .distance((d) => (d.type === 'contains' ? 55 : 85))
        .strength((d) => (d.type === 'contains' ? 0.6 : 0.35))
    )
    .force('charge', forceManyBody().strength(-160).distanceMax(380))
    .force('collide', forceCollide((d) => d.radius + 18).iterations(1))
    .force('x', forceX((d) => clusterCenters[d.group]?.x || 0).strength(0.35))
    .force('y', forceY((d) => clusterCenters[d.group]?.y || 0).strength(0.35))
    .stop()

  const ticks = simulationNodes.length > 250 ? 40 : 50
  for (let i = 0; i < ticks; ++i) sim.tick()

  // 6. Compute bounding hulls for module groups (clean cards with ample padding)
  const groupBounds = {}
  simulationNodes.forEach((node) => {
    const grp = node.group
    if (!groupBounds[grp]) {
      groupBounds[grp] = {
        minX: Infinity,
        maxX: -Infinity,
        minY: Infinity,
        maxY: -Infinity,
        count: 0,
        group: grp,
      }
    }
    const r = node.radius
    groupBounds[grp].minX = Math.min(groupBounds[grp].minX, node.x - r)
    groupBounds[grp].maxX = Math.max(groupBounds[grp].maxX, node.x + r)
    groupBounds[grp].minY = Math.min(groupBounds[grp].minY, node.y - r)
    groupBounds[grp].maxY = Math.max(groupBounds[grp].maxY, node.y + r)
    groupBounds[grp].count += 1
  })

  const padding = 36
  const headerHeight = 36

  const hullNodes = Object.entries(groupBounds)
    .filter(([grp, b]) => grp !== 'external' && grp !== 'misc' && b.count >= 2)
    .slice(0, 15)
    .map(([grp, b]) => {
      const width = Math.max(200, b.maxX - b.minX + padding * 2)
      const height = Math.max(120, b.maxY - b.minY + padding * 2 + headerHeight)
      return {
        id: `hull_${grp}`,
        type: 'fileHull',
        position: {
          x: b.minX - padding,
          y: b.minY - padding - headerHeight,
        },
        data: {
          file: grp,
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

  // 7. Format ReactFlow circular nodes
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
        group: n.group,
        radius: config.radius,
        color: config.color,
        border: config.border,
        icon: config.icon,
        change_frequency: n.raw.change_frequency || 0,
        loc: n.raw.loc || 0,
        complexity: n.raw.complexity || 1,
        hotspot_score: n.raw.hotspot_score || 0,
        is_keystone: Boolean(n.raw.is_keystone),
        has_circular_dependency: Boolean(n.raw.has_circular_dependency),
      },
      zIndex: 10,
    }
  })

  const allNodes = [...hullNodes, ...reactFlowNodes]

  // 8. Format edges with vibrant, high-contrast aesthetics and visible flow
  const edges = validEdges.map((e, index) => {
    const sourceId = typeof e.source === 'object' && e.source !== null ? e.source.id : e.source
    const targetId = typeof e.target === 'object' && e.target !== null ? e.target.id : e.target
    const edgeType = e.type || 'calls'

    let stroke = '#38BDF8' // High-visibility Sky Blue for calls
    let strokeDasharray = undefined
    let strokeWidth = 1.4
    let opacity = 0.45

    if (edgeType === 'contains') {
      stroke = '#A78BFA' // Lavender
      strokeDasharray = '4 4'
      strokeWidth = 1.3
      opacity = 0.55
    } else if (edgeType === 'imports') {
      stroke = '#818CF8' // Indigo
      strokeDasharray = '6 3'
      strokeWidth = 1.2
      opacity = 0.4
    } else if (edgeType === 'instantiates') {
      stroke = '#34D399' // Emerald
      strokeWidth = 1.6
      opacity = 0.6
    }

    return {
      id: `e-${index}-${sourceId}-${targetId}`,
      source: sourceId,
      target: targetId,
      type: 'default',
      animated: false,
      style: {
        stroke,
        strokeWidth,
        opacity,
        strokeDasharray,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: stroke,
        width: 11,
        height: 11,
      },
      data: {
        baseStroke: stroke,
        baseStrokeWidth: strokeWidth,
        edgeType,
        sourceId,
        targetId,
      },
    }
  })

  return { nodes: allNodes, edges, fileHulls: hullNodes }
}
