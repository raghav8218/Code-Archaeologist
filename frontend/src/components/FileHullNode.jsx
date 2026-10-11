import React, { memo } from 'react'
import { FileCode } from 'lucide-react'

function FileHullNode({ data }) {
  const { file, symbolCount, width, height } = data

  const fileName = file.split('/').pop()
  const dirPath = file.includes('/') ? file.substring(0, file.lastIndexOf('/')) : ''

  return (
    <div
      className="file-hull-container"
      style={{
        width,
        height,
        background: 'rgba(30, 41, 59, 0.45)',
        border: '1px solid rgba(71, 85, 105, 0.5)',
        borderRadius: '14px',
        pointerEvents: 'none',
        position: 'relative',
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.25)',
      }}
    >
      <div className="file-hull-header">
        <FileCode size={13} className="file-hull-icon" />
        <span className="file-hull-name">
          {dirPath && <span className="file-hull-dir">{dirPath}/</span>}
          <strong>{fileName}</strong>
        </span>
        <span className="file-hull-badge">{symbolCount} {symbolCount === 1 ? 'symbol' : 'symbols'}</span>
      </div>
    </div>
  )
}

export default memo(FileHullNode)
