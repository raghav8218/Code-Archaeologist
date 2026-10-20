import React, { memo } from 'react'
import { FolderTree } from 'lucide-react'

function FileHullNode({ data }) {
  const { file, symbolCount, width, height } = data

  return (
    <div
      className="file-hull-container"
      style={{
        width,
        height,
        background: 'rgba(15, 23, 42, 0.55)',
        border: '1px solid rgba(56, 189, 248, 0.25)',
        borderRadius: '16px',
        pointerEvents: 'none',
        position: 'relative',
        boxShadow: '0 4px 24px rgba(0, 0, 0, 0.4)',
      }}
    >
      <div className="file-hull-header">
        <FolderTree size={13} className="file-hull-icon" style={{ color: '#38BDF8' }} />
        <span className="file-hull-name">
          <strong style={{ color: '#F1F5F9' }}>{file}</strong>
        </span>
        <span className="file-hull-badge">{symbolCount} {symbolCount === 1 ? 'symbol' : 'symbols'}</span>
      </div>
    </div>
  )
}

export default memo(FileHullNode)
