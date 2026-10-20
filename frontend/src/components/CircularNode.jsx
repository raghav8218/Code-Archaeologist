import React, { memo, useContext } from 'react'
import { Handle, Position } from 'reactflow'
import { GraphInteractionContext } from './GraphView'

function CircularNode({ id, data, selected }) {
  const interaction = useContext(GraphInteractionContext)

  const {
    label,
    kind,
    radius = 16,
    color,
    border,
    icon,
    change_frequency = 0,
    complexity = 1,
    hotspot_score = 0,
    is_keystone = false,
    has_circular_dependency = false,
  } = data

  const hoveredNodeId = interaction?.hoveredNodeId
  const isHoverActive = Boolean(hoveredNodeId)
  const isCurrentHover = id === hoveredNodeId
  const isCaller = isHoverActive && Boolean(interaction?.hoveredCallers?.has(id))
  const isCallee = isHoverActive && Boolean(interaction?.hoveredCallees?.has(id))
  const isConnected = isCurrentHover || isCaller || isCallee
  const isDimmed = isHoverActive && !isConnected

  const isSelected = selected || interaction?.selectedId === id || (data.raw && interaction?.selectedId === data.raw.id)

  const isSearchMatch =
    interaction?.searchQuery &&
    interaction.searchQuery.trim().length > 0 &&
    ((label && label.toLowerCase().includes(interaction.searchQuery.toLowerCase())) ||
      (data.file && data.file.toLowerCase().includes(interaction.searchQuery.toLowerCase())))

  const isHighlighted =
    (interaction?.highlightedIds && (interaction.highlightedIds.includes(id) || (data.raw && interaction.highlightedIds.includes(data.raw.id)))) ||
    isSearchMatch ||
    isSelected

  const diameter = radius * 2

  // CodeScene Hotspot Formula: Complexity * log2(Churn + 1)
  const effectiveHotspotScore = hotspot_score > 0
    ? hotspot_score
    : (change_frequency > 0 ? Math.round(complexity * Math.log2(change_frequency + 1)) : 0)

  const isHotspot = effectiveHotspotScore >= 4
  const hotspotRing = isHotspot ? Math.min(7, 2 + Math.log2(effectiveHotspotScore + 1)) : 0

  let currentOpacity = 1.0
  if (isDimmed) {
    currentOpacity = 0.22
  }

  let ringColor = 'transparent'
  if (isHighlighted || isSelected) {
    ringColor = '#38BDF8'
  } else if (isCaller) {
    ringColor = '#06B6D4' // Electric Cyan for caller
  } else if (isCallee) {
    ringColor = '#F43F5E' // Rose for callee
  } else if (isCurrentHover) {
    ringColor = '#F8FAFC'
  } else if (isHotspot) {
    ringColor = 'rgba(239, 68, 68, 0.75)' // CodeScene Hotspot Red
  }

  return (
    <div
      className={`circular-node-wrapper ${isDimmed ? 'is-dimmed' : ''} ${isCurrentHover ? 'is-hovered' : ''}`}
      style={{
        opacity: currentOpacity,
        transition: 'opacity 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
      }}
    >
      {/* Main Circle */}
      <div
        className="circular-node-circle"
        style={{
          width: diameter,
          height: diameter,
          backgroundColor: color,
          borderColor: border,
          transform: isCurrentHover || isHighlighted ? 'scale(1.14)' : 'scale(1)',
          transition: 'transform 0.18s ease, box-shadow 0.18s ease',
          boxShadow:
            ringColor !== 'transparent'
              ? `0 0 0 ${isHighlighted ? 4 : hotspotRing || 3}px ${ringColor}, 0 0 16px ${color}80`
              : `0 0 12px ${color}40`,
        }}
      >
        <Handle
          type="target"
          position={Position.Top}
          id="t"
          className="rf-handle"
          isConnectable={false}
        />
        <Handle
          type="source"
          position={Position.Bottom}
          id="b"
          className="rf-handle"
          isConnectable={false}
        />
        <Handle
          type="target"
          position={Position.Left}
          id="l"
          className="rf-handle"
          isConnectable={false}
        />
        <Handle
          type="source"
          position={Position.Right}
          id="r"
          className="rf-handle"
          isConnectable={false}
        />

        <span className="circular-node-icon" style={{ fontSize: Math.max(10, radius * 0.75) }}>
          {icon}
        </span>
      </div>

      {/* Symbol Label & Badges (no native title attributes to prevent browser mouseleave flickering) */}
      <div className="circular-node-label-container">
        <span className={`circular-node-label ${isHighlighted ? 'highlighted' : ''}`}>
          {label}
        </span>

        {/* CodeScene Hotspot Badge */}
        {isHotspot && (
          <span className="circular-node-churn-badge">
            🔥{effectiveHotspotScore}
          </span>
        )}

        {/* Keystone Badge (PageRank hub) */}
        {is_keystone && (
          <span className="circular-node-keystone-badge">
            👑
          </span>
        )}

        {/* Circular Dependency Warning */}
        {has_circular_dependency && (
          <span className="circular-node-cycle-badge">
            ⟲
          </span>
        )}
      </div>

      {/* Sleek Custom In-Canvas Tooltip (pointer-events: none, strictly inside canvas) */}
      {isCurrentHover && (
        <div className="node-hover-tooltip">
          <div className="tooltip-kind">{kind} {is_keystone ? '• Keystone Hub' : ''}</div>
          <div className="tooltip-title">{data.qualified_name || label}</div>
          {data.file && <div className="tooltip-file">{data.file}</div>}
          <div className="tooltip-metrics">
            <span>LOC: {data.loc || 1}</span>
            <span>Complexity: {complexity}</span>
            {change_frequency > 0 && <span>Commits: {change_frequency}</span>}
          </div>
          {isHotspot && (
            <div className="tooltip-churn">
              🔥 CodeScene Hotspot Score: {effectiveHotspotScore}
            </div>
          )}
          {has_circular_dependency && (
            <div className="tooltip-cycle-warning">
              ⚠️ Part of a circular dependency loop
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default memo(CircularNode)
