import React, { memo } from 'react'
import { Handle, Position } from 'reactflow'

function CircularNode({ data, selected }) {
  const {
    label,
    kind,
    radius = 16,
    color,
    border,
    icon,
    change_frequency = 0,
    isHighlighted = false,
    isHovered = false,
    isDimmed = false,
    isCaller = false,
    isCallee = false,
  } = data

  const diameter = radius * 2

  // Churn hotspot border intensity
  const hasHotspot = change_frequency > 0
  const hotspotRing = hasHotspot ? Math.min(6, 2 + Math.log2(change_frequency + 1)) : 0

  let currentOpacity = 1.0
  if (isDimmed) {
    currentOpacity = 0.2
  }

  let ringColor = 'transparent'
  if (isHighlighted || selected) {
    ringColor = '#38BDF8'
  } else if (isCaller) {
    ringColor = '#06B6D4' // Electric Cyan for caller
  } else if (isCallee) {
    ringColor = '#F43F5E' // Rose for callee
  } else if (isHovered) {
    ringColor = '#F8FAFC'
  } else if (hasHotspot) {
    ringColor = 'rgba(239, 68, 68, 0.7)' // Reddish hotspot
  }

  return (
    <div
      className={`circular-node-wrapper ${isDimmed ? 'is-dimmed' : ''} ${isHovered ? 'is-hovered' : ''}`}
      style={{
        opacity: currentOpacity,
        transition: 'opacity 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
      }}
    >
      {/* Main Circle (with static handles attached to its edges) */}
      <div
        className="circular-node-circle"
        style={{
          width: diameter,
          height: diameter,
          backgroundColor: color,
          borderColor: border,
          transform: isHovered || isHighlighted ? 'scale(1.12)' : 'scale(1)',
          transition: 'transform 0.18s ease, box-shadow 0.18s ease',
          boxShadow:
            ringColor !== 'transparent'
              ? `0 0 0 ${isHighlighted ? 4 : hotspotRing || 3}px ${ringColor}, 0 0 16px ${color}80`
              : `0 0 12px ${color}40`,
        }}
      >
        {/* Handles attached to the 4 sides of the circle */}
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

      {/* Symbol Label (without native OS title tooltip to prevent mouse-leave flickering) */}
      <div className="circular-node-label-container">
        <span className={`circular-node-label ${isHighlighted ? 'highlighted' : ''}`}>
          {label}
        </span>
        {hasHotspot && (
          <span className="circular-node-churn-badge">
            ↻{change_frequency}
          </span>
        )}
      </div>

      {/* Sleek Custom In-Canvas Tooltip (pointer-events: none, so it never flickers) */}
      {isHovered && (
        <div className="node-hover-tooltip">
          <div className="tooltip-kind">{kind}</div>
          <div className="tooltip-title">{data.qualified_name || label}</div>
          {data.file && <div className="tooltip-file">{data.file}</div>}
          {hasHotspot && (
            <div className="tooltip-churn">
              Changed in {change_frequency} commit{change_frequency === 1 ? '' : 's'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default memo(CircularNode)
