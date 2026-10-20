import React, { useState, useMemo, useEffect, useCallback, useRef, createContext } from 'react'
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
import { Search, Crosshair, Compass, FolderTree, Layers } from 'lucide-react'

import CircularNode from './CircularNode.jsx'
import FileHullNode from './FileHullNode.jsx'
import { layoutGraph, NODE_CONFIG } from '../utils/layout'

// Export context so CircularNode can read hover state directly without triggering setNodes
export const GraphInteractionContext = createContext({
  hoveredNodeId: null,
  isHoverActive: false,
  hoveredCallers: new Set(),
  hoveredCallees: new Set(),
  highlightedIds: [],
  selectedId: null,
  searchQuery: '',
})

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
  jumpToNodeId = null,
}) {
  const reactFlowInstance = useReactFlow()
  const [hoveredNodeId, setHoveredNodeId] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')

  const isLargeRepo = rawNodes.length > 120
  const [viewMode, setViewMode] = useState(isLargeRepo ? 'backbone' : 'all')
  const [selectedModule, setSelectedModule] = useState('all')

  // Extract all distinct module paths for drill-down
  const allModules = useMemo(() => {
    const set = new Set()
    rawNodes.forEach((n) => {
      if (n.file && n.file !== 'misc' && n.file !== 'external') {
        const parts = n.file.split(/[/\\]/)
        const folder = parts.length > 1 ? parts.slice(0, -1).join('/') : n.file
        set.add(folder)
      }
    })
    return Array.from(set).sort()
  }, [rawNodes])

  // Filter raw nodes according to progressive semantic disclosure
  const { filteredRawNodes, filteredRawEdges } = useMemo(() => {
    if (viewMode === 'all') {
      return { filteredRawNodes: rawNodes, filteredRawEdges: rawEdges }
    }

    if (viewMode === 'module' && selectedModule !== 'all') {
      const matched = rawNodes.filter(
        (n) => n.file && n.file.startsWith(selectedModule)
      )
      const matchedIds = new Set(matched.map((n) => n.id))
      const edges = rawEdges.filter(
        (e) => matchedIds.has(e.source) && matchedIds.has(e.target)
      )
      return { filteredRawNodes: matched, filteredRawEdges: edges }
    }

    // Default 'backbone' view: Routes, Classes, Keystones (👑), Hotspots (🔥)
    const backboneNodes = rawNodes.filter((n) => {
      if (n.is_route || n.kind === 'route') return true
      if (n.kind === 'class') return true
      if (n.is_keystone) return true
      if (n.hotspot_score && n.hotspot_score > 0) return true
      if (n.change_frequency && n.change_frequency >= 2) return true
      if (selectedNode && (selectedNode.id === n.id || selectedNode.id === n.raw_id)) return true
      return false
    })

    let resultNodes = backboneNodes
    if (resultNodes.length < 15 && rawNodes.length > 0) {
      resultNodes = rawNodes.slice(0, 75)
    }

    const nodeIds = new Set(resultNodes.map((n) => n.id))
    const edges = rawEdges.filter(
      (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
    )

    return { filteredRawNodes: resultNodes, filteredRawEdges: edges }
  }, [rawNodes, rawEdges, viewMode, selectedModule, selectedNode])

  // Ensure cited nodes from Q&A become visible if currently filtered out
  useEffect(() => {
    if (!jumpToNodeId) return
    const exists = filteredRawNodes.some(
      (n) => n.id === jumpToNodeId || n.raw_id === jumpToNodeId
    )
    if (!exists) {
      setViewMode('all')
    }
  }, [jumpToNodeId, filteredRawNodes])

  // Active symbol filter chips
  const [activeFilters, setActiveFilters] = useState({
    class: true,
    route: true,
    function: true,
    method: true,
    external: false,
  })

  // Pre-calculate initial organic layout on filtered nodes
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => layoutGraph(filteredRawNodes, filteredRawEdges),
    [filteredRawNodes, filteredRawEdges]
  )

  // Standard ReactFlow state hooks
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  // Initialize nodes and edges on layout or filter changes (NEVER on hover!)
  useEffect(() => {
    const formatted = initialNodes.map((n) => {
      if (n.type === 'fileHull') return n
      const kind = n.data?.kind || 'function'
      const isVisible = activeFilters[kind] !== false
      return {
        ...n,
        hidden: !isVisible,
      }
    })
    setNodes(formatted)
    setEdges(initialEdges)
  }, [initialNodes, initialEdges, activeFilters, setNodes, setEdges])

  // Build connectivity map for caller/callee highlighting
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

  // Stable interaction context value (passed to CircularNode components)
  const interactionValue = useMemo(() => {
    const isHoverActive = Boolean(hoveredNodeId)
    const hoveredCallers = connectivityMap.callers.get(hoveredNodeId) || new Set()
    const hoveredCallees = connectivityMap.callees.get(hoveredNodeId) || new Set()
    const selectedId = selectedNode?.id || selectedNode?.raw?.id || null

    return {
      hoveredNodeId,
      isHoverActive,
      hoveredCallers,
      hoveredCallees,
      highlightedIds,
      selectedId,
      searchQuery,
    }
  }, [hoveredNodeId, connectivityMap, selectedNode, highlightedIds, searchQuery])

  // Update edge visual styles on hover or selection (SVG paths with pointer-events: none)
  useEffect(() => {
    const isHoverActive = Boolean(hoveredNodeId)

    setEdges((currentEdges) =>
      currentEdges.map((e) => {
        const sourceId = e.source
        const targetId = e.target

        const isCallerEdge = isHoverActive && targetId === hoveredNodeId
        const isCalleeEdge = isHoverActive && sourceId === hoveredNodeId
        const isHighlighted =
          (highlightedIds.includes(sourceId) && highlightedIds.includes(targetId)) ||
          (selectedNode && (selectedNode.id === sourceId || selectedNode.id === targetId))

        let stroke = e.data?.baseStroke || '#38BDF8'
        let strokeWidth = e.data?.baseStrokeWidth || 1.4
        let opacity = 0.45
        let animated = false

        if (isHoverActive) {
          if (isCallerEdge) {
            stroke = '#06B6D4' // Electric Cyan for caller
            strokeWidth = 2.8
            opacity = 1.0
            animated = true
          } else if (isCalleeEdge) {
            stroke = '#F43F5E' // Rose for callee
            strokeWidth = 2.8
            opacity = 1.0
            animated = true
          } else {
            opacity = 0.08 // Dim non-connected edges cleanly
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
            transition: 'opacity 0.18s ease, stroke-width 0.18s ease, stroke 0.18s ease',
          },
          markerEnd: {
            ...e.markerEnd,
            color: stroke,
          },
        }
      })
    )
  }, [hoveredNodeId, highlightedIds, selectedNode, setEdges])

  // Single-fire citation jump ref (prevents infinite camera oscillation)
  const lastHandledJumpRef = useRef(null)

  useEffect(() => {
    if (!jumpToNodeId || !reactFlowInstance || initialNodes.length === 0) return
    if (lastHandledJumpRef.current === jumpToNodeId) return

    const target = initialNodes.find(
      (n) =>
        n.id === jumpToNodeId ||
        n.data?.id === jumpToNodeId ||
        n.data?.raw?.id === jumpToNodeId ||
        n.data?.raw?.raw_id === jumpToNodeId ||
        n.data?.raw?.name === jumpToNodeId
    )
    if (target && Number.isFinite(target.position?.x) && Number.isFinite(target.position?.y)) {
      lastHandledJumpRef.current = jumpToNodeId
      reactFlowInstance.setCenter(
        target.position.x + (target.data?.radius || 16),
        target.position.y + (target.data?.radius || 16),
        {
          zoom: 1.35,
          duration: 600,
        }
      )
    }
  }, [jumpToNodeId, reactFlowInstance, initialNodes])

  // Smooth fitView when view mode or module changes
  useEffect(() => {
    if (!reactFlowInstance || initialNodes.length === 0) return
    const timer = setTimeout(() => {
      reactFlowInstance.fitView({ padding: 0.22, duration: 500 })
    }, 60)
    return () => clearTimeout(timer)
  }, [viewMode, selectedModule, reactFlowInstance])

  // Stable hover callbacks that NEVER mutate nodes array
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
        n.data?.label &&
        n.data.label.toLowerCase().includes(searchQuery.toLowerCase())
    )
    if (match && reactFlowInstance) {
      reactFlowInstance.setCenter(
        match.position.x + (match.data?.radius || 16),
        match.position.y + (match.data?.radius || 16),
        {
          zoom: 1.4,
          duration: 600,
        }
      )
      if (match.data?.raw) {
        onNodeClick(match.data.raw)
      }
    }
  }

  const toggleFilter = (kind) => {
    setActiveFilters((prev) => ({ ...prev, [kind]: !prev[kind] }))
  }

  // Fit view once on initial load
  const onInit = useCallback(
    (instance) => {
      setTimeout(() => {
        instance.fitView({ padding: 0.22, duration: 500 })
      }, 70)
    },
    []
  )

  return (
    <GraphInteractionContext.Provider value={interactionValue}>
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

          {/* Progressive Semantic Disclosure View Selector */}
          <div className="graph-viewmode-group">
            <button
              type="button"
              className={`viewmode-btn ${viewMode === 'backbone' ? 'active' : ''}`}
              onClick={() => {
                setViewMode('backbone')
                setSelectedModule('all')
              }}
              title="Display curated architectural hubs (Routes, Classes, PageRank Keystones 👑, Hotspots 🔥)"
            >
              <Compass size={13} />
              <span>Backbone</span>
              {isLargeRepo && <span className="backbone-badge">Fast</span>}
            </button>

            {allModules.length > 1 && (
              <div className="module-select-wrapper">
                <FolderTree size={13} className="module-icon" />
                <select
                  value={viewMode === 'module' ? selectedModule : 'all'}
                  onChange={(e) => {
                    if (e.target.value === 'all') {
                      setViewMode('backbone')
                      setSelectedModule('all')
                    } else {
                      setViewMode('module')
                      setSelectedModule(e.target.value)
                    }
                  }}
                  className="module-select-dropdown"
                  title="Focus on a specific module or subsystem"
                >
                  <option value="all">Module Focus...</option>
                  {allModules.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <button
              type="button"
              className={`viewmode-btn ${viewMode === 'all' ? 'active' : ''}`}
              onClick={() => setViewMode('all')}
              title="Display all raw symbols in the repository"
            >
              <Layers size={13} />
              <span>All ({rawNodes.length})</span>
            </button>
          </div>

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
          onlyRenderVisibleElements={true}
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
    </GraphInteractionContext.Provider>
  )
}

export default function GraphView(props) {
  return (
    <ReactFlowProvider>
      <GraphViewInner {...props} />
    </ReactFlowProvider>
  )
}
