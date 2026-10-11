import React, { useState, useMemo, useEffect, useCallback } from 'react'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useReactFlow,
  useNodesState,
  useEdgesState,
  ReactFlowProvider,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { Search, Crosshair } from 'lucide-react'

import CircularNode from './CircularNode.jsx'
import FileHullNode from './FileHullNode.jsx'
import { layoutGraph, NODE_CONFIG } from '../utils/layout'

const nodeTypes = {
  circularNode: CircularNode,
  fileHull: FileHullNode,
}

function GraphViewInner({
  rawNodes = [],
  rawEdges = [],
  highlightedIds = [],
  selectedNode = null,
  onNodeClick,
}) {
  const reactFlowInstance = useReactFlow()
  const [hoveredNodeId, setHoveredNodeId] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')

  // Utility is OFF by default to eliminate chaotic spaghetti clutter
  const [activeFilters, setActiveFilters] = useState({
    class: true,
    route: true,
    function: true,
    method: true,
    external: false, // Default off for clean architecture
  })

  // Pre-calculate initial layout
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => layoutGraph(rawNodes, rawEdges),
    [rawNodes, rawEdges]
  )

  // Standard ReactFlow draggable state hooks
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  // Initialize nodes and edges on data load
  useEffect(() => {
    setNodes(initialNodes)
    setEdges(initialEdges)
  }, [initialNodes, initialEdges, setNodes, setEdges])

  // Map callers and callees for fast lookup
  const connectivityMap = useMemo(() => {
    const callers = new Map() // target -> Set of sources
    const callees = new Map() // source -> Set of targets

    initialEdges.forEach((e) => {
      const s = e.source
      const t = e.target

      if (!callees.has(s)) callees.set(s, new Set())
      callees.get(s).add(t)

      if (!callers.has(t)) callers.set(t, new Set())
      callers.get(t).add(s)
    })

    return { callers, callees }
  }, [initialEdges])

  // Update node visibility, dimming, and highlight without recreating positions
  useEffect(() => {
    const isHoverActive = Boolean(hoveredNodeId)
    const hoveredCallers = connectivityMap.callers.get(hoveredNodeId) || new Set()
    const hoveredCallees = connectivityMap.callees.get(hoveredNodeId) || new Set()

    setNodes((currentNodes) =>
      currentNodes.map((node) => {
        if (node.type === 'fileHull') return node

        const kind = node.data.kind || 'function'
        const isVisible = activeFilters[kind] !== false

        const isSearchMatch =
          searchQuery.trim().length > 0 &&
          (node.data.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
            (node.data.file && node.data.file.toLowerCase().includes(searchQuery.toLowerCase())))

        const isSelected =
          selectedNode && (selectedNode.id === node.id || selectedNode.id === node.data.raw?.id)
        const isHighlighted =
          highlightedIds.includes(node.id) ||
          highlightedIds.includes(node.data.raw?.id) ||
          isSearchMatch

        const isCurrentHover = node.id === hoveredNodeId
        const isCaller = isHoverActive && hoveredCallers.has(node.id)
        const isCallee = isHoverActive && hoveredCallees.has(node.id)
        const isConnected = isCurrentHover || isCaller || isCallee
        const isDimmed = isHoverActive && !isConnected

        return {
          ...node,
          hidden: !isVisible,
          data: {
            ...node.data,
            isHighlighted: isHighlighted || isSelected,
            isHovered: isCurrentHover,
            isDimmed,
            isCaller,
            isCallee,
          },
        }
      })
    )
  }, [
    hoveredNodeId,
    connectivityMap,
    highlightedIds,
    selectedNode,
    activeFilters,
    searchQuery,
    setNodes,
  ])

  // Update edge styles on hover or selection (with clean subtle defaults)
  useEffect(() => {
    const isHoverActive = Boolean(hoveredNodeId)

    // Set of currently visible node IDs
    const visibleKinds = new Set(
      Object.keys(activeFilters).filter((k) => activeFilters[k] !== false)
    )

    setEdges((currentEdges) =>
      currentEdges.map((e) => {
        const sourceId = e.source
        const targetId = e.target

        const isConnectingHover =
          isHoverActive && (sourceId === hoveredNodeId || targetId === hoveredNodeId)
        const isCallerEdge = isHoverActive && targetId === hoveredNodeId
        const isCalleeEdge = isHoverActive && sourceId === hoveredNodeId

        const isHighlighted =
          (highlightedIds.includes(sourceId) && highlightedIds.includes(targetId)) ||
          (selectedNode && (selectedNode.id === sourceId || selectedNode.id === targetId))

        let stroke = e.data?.baseStroke || '#64748B'
        let strokeWidth = 1.3
        let opacity = 0.22 // Subtle and calm by default
        let animated = false

        if (isHoverActive) {
          if (isCallerEdge) {
            stroke = '#06B6D4' // Electric Cyan for caller
            strokeWidth = 2.6
            opacity = 1.0
            animated = true
          } else if (isCalleeEdge) {
            stroke = '#F43F5E' // Rose for callee
            strokeWidth = 2.6
            opacity = 1.0
            animated = true
          } else {
            opacity = 0.05 // Dim all non-connected edges to near-zero
          }
        } else if (isHighlighted) {
          stroke = '#38BDF8'
          strokeWidth = 2.6
          opacity = 1.0
          animated = true
        }

        return {
          ...e,
          animated,
          style: {
            ...e.style,
            stroke,
            strokeWidth,
            opacity,
            transition: 'opacity 0.2s ease, stroke-width 0.2s ease, stroke 0.2s ease',
          },
          markerEnd: {
            ...e.markerEnd,
            color: stroke,
          },
        }
      })
    )
  }, [hoveredNodeId, highlightedIds, selectedNode, activeFilters, setEdges])

  // Stable hover callbacks
  const handleNodeMouseEnter = useCallback((_, node) => {
    if (node.type === 'circularNode') {
      setHoveredNodeId(node.id)
    }
  }, [])

  const handleNodeMouseLeave = useCallback((_, node) => {
    if (node.type === 'circularNode') {
      setHoveredNodeId((curr) => (curr === node.id ? null : curr))
    }
  }, [])

  const handlePaneMouseEnter = useCallback(() => {
    setHoveredNodeId(null)
  }, [])

  // Center on node if search finds match
  const handleSearchSubmit = (e) => {
    e.preventDefault()
    if (!searchQuery.trim()) return
    const match = nodes.find(
      (n) =>
        n.type === 'circularNode' &&
        n.data.label.toLowerCase().includes(searchQuery.toLowerCase())
    )
    if (match && reactFlowInstance) {
      reactFlowInstance.setCenter(match.position.x, match.position.y, {
        zoom: 1.4,
        duration: 600,
      })
      onNodeClick(match.data.raw)
    }
  }

  const toggleFilter = (kind) => {
    setActiveFilters((prev) => ({ ...prev, [kind]: !prev[kind] }))
  }

  // Fit view once on initial load
  const onInit = useCallback(
    (instance) => {
      setTimeout(() => {
        instance.fitView({ padding: 0.22, duration: 600 })
      }, 50)
    },
    []
  )

  return (
    <div className="graph-container">
      {/* Top Filter and Search Bar */}
      <div className="graph-toolbar">
        <form onSubmit={handleSearchSubmit} className="graph-search-form">
          <Search size={14} className="graph-search-icon" />
          <input
            type="text"
            placeholder="Find symbol (e.g. parse, /api)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="graph-search-input"
          />
        </form>

        <div className="graph-filter-chips">
          {Object.entries(NODE_CONFIG).map(([kind, cfg]) => {
            const active = activeFilters[kind] !== false
            return (
              <button
                key={kind}
                type="button"
                className={`graph-filter-chip ${active ? 'active' : ''}`}
                onClick={() => toggleFilter(kind)}
                style={{
                  '--chip-color': cfg.color,
                }}
              >
                <span className="chip-dot" style={{ backgroundColor: cfg.color }} />
                <span className="chip-label">{cfg.label}</span>
              </button>
            )
          })}
        </div>

        <button
          type="button"
          className="graph-fit-btn"
          onClick={() => reactFlowInstance?.fitView({ duration: 500, padding: 0.22 })}
          title="Fit View"
        >
          <Crosshair size={14} />
          <span>Center</span>
        </button>
      </div>

      {/* Main ReactFlow Graph with DRAGGABLE nodes and stable viewport */}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => {
          if (node.type === 'circularNode' && node.data?.raw) {
            onNodeClick(node.data.raw)
          }
        }}
        onNodeMouseEnter={handleNodeMouseEnter}
        onNodeMouseLeave={handleNodeMouseLeave}
        onPaneMouseEnter={handlePaneMouseEnter}
        onInit={onInit}
        nodesDraggable={true}
        elementsSelectable={true}
        proOptions={{ hideAttribution: true }}
        minZoom={0.15}
        maxZoom={2.5}
      >
        <Background color="#1E293B" gap={24} size={1} />
        <Controls className="rf-dark-controls" />
        <MiniMap
          nodeColor={(node) => {
            if (node.type === 'fileHull') return 'rgba(30, 41, 59, 0.4)'
            return node.data?.color || '#06B6D4'
          }}
          maskColor="rgba(11, 15, 25, 0.85)"
          style={{ background: '#0B0F19', border: '1px solid rgba(255,255,255,0.08)' }}
        />
      </ReactFlow>

      {/* Active Hover Tooltip Indicator */}
      {hoveredNodeId && (
        <div className="hover-focus-legend">
          <span className="hover-focus-dot caller-dot" /> Incoming Caller
          <span className="hover-focus-dot callee-dot" /> Outgoing Callee
        </div>
      )}
    </div>
  )
}

export default function GraphView(props) {
  return (
    <ReactFlowProvider>
      <GraphViewInner {...props} />
    </ReactFlowProvider>
  )
}
