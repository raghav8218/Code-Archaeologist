import React, { useEffect, useState, useMemo } from 'react'
import {
  Code,
  GitCommit,
  GitPullRequest,
  Activity,
  ArrowRight,
  CornerDownRight,
  Copy,
  Check,
  ChevronRight,
  X,
  FileCode,
  Flame,
  FileText,
} from 'lucide-react'
import { NODE_CONFIG } from '../utils/layout'

export default function NodeInspector({
  repoId,
  selected,
  onClose,
  onTrace,
  onSelectSymbol,
}) {
  const [details, setDetails] = useState(null)
  const [loading, setLoading] = useState(false)
  const [copiedCode, setCopiedCode] = useState(false)

  // Fetch full details (callers, callees, git blame) when a node is selected
  useEffect(() => {
    if (!selected) {
      setDetails(null)
      return
    }

    // Initialize details with selected node immediately so source displays instantly
    setDetails(selected)

    if (!repoId) return

    setLoading(true)
    const symbolId = selected.id || selected.raw_id

    fetch(`/api/symbol/${repoId}?id=${encodeURIComponent(symbolId)}`)
      .then((res) => {
        if (!res.ok) throw new Error('Symbol details not found')
        return res.json()
      })
      .then((data) => {
        setDetails((prev) => ({
          ...prev,
          ...data,
          // Preserve source if details didn't have it or vice versa
          source: data.source || selected.source || prev?.source,
        }))
      })
      .catch((err) => {
        console.warn('Symbol details fetch failed, using local node data:', err)
      })
      .finally(() => setLoading(false))
  }, [selected, repoId])

  if (!selected) {
    return (
      <div className="inspector-empty">
        <div className="inspector-empty-card">
          <Code size={28} className="inspector-empty-icon" />
          <h4>Symbol Inspector</h4>
          <p>Click any node in the graph to inspect its source code, complexity, callers, and git history.</p>
        </div>
      </div>
    )
  }

  const kind = selected.kind || 'function'
  const config = NODE_CONFIG[kind] || NODE_CONFIG.function
  const data = details || selected

  const handleCopyCode = () => {
    const code = data.source || data.signature || ''
    if (!code) return
    navigator.clipboard.writeText(code)
    setCopiedCode(true)
    setTimeout(() => setCopiedCode(false), 2000)
  }

  // Cyclomatic complexity categorization
  const complexity = data.complexity || 1
  let complexityLabel = 'Low'
  let complexityColor = '#10B981'
  if (complexity > 10) {
    complexityLabel = 'High'
    complexityColor = '#EF4444'
  } else if (complexity > 5) {
    complexityLabel = 'Moderate'
    complexityColor = '#F59E0B'
  }

  const startLine = data.start_line || 1
  const sourceCode = data.source || data.signature || ''
  const codeLines = sourceCode ? sourceCode.split('\n') : []

  return (
    <div className="node-inspector">
      {/* Top Header */}
      <div className="inspector-header">
        <div className="inspector-title-row">
          <span
            className="symbol-kind-badge"
            style={{ backgroundColor: `${config.color}20`, color: config.color, borderColor: config.border }}
          >
            {config.label}
          </span>
          <h3 className="symbol-name">{data.label || data.name}</h3>
          {onClose && (
            <button type="button" className="inspector-close-btn" onClick={onClose} title="Close Inspector">
              <X size={16} />
            </button>
          )}
        </div>

        <div className="symbol-location">
          <FileCode size={13} />
          <span>
            {data.file}:{startLine}
            {data.end_line && data.end_line !== startLine ? `-${data.end_line}` : ''}
          </span>
        </div>
      </div>

      {loading && <div className="inspector-loading-bar" />}

      <div className="inspector-scroll-body">
        {/* Metric Cards Grid */}
        <div className="metrics-grid">
          <div className="metric-card">
            <span className="metric-label">LOC</span>
            <span className="metric-value">{data.loc || (data.end_line ? data.end_line - startLine + 1 : 1)}</span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Complexity</span>
            <div className="metric-value-row">
              <span className="metric-value">{complexity}</span>
              <span className="metric-sub" style={{ color: complexityColor }}>{complexityLabel}</span>
            </div>
          </div>

          <div className="metric-card">
            <span className="metric-label">Churn</span>
            <div className="metric-value-row">
              <span className="metric-value">{data.change_frequency || 0}</span>
              {data.change_frequency > 0 && <Flame size={14} className="hotspot-flame-icon" />}
            </div>
          </div>
        </div>

        {/* PRIMARY: SOURCE CODE (Always shown prominently right at top) */}
        <div className="inspector-section source-section-prominent">
          <div className="section-header-row">
            <div className="source-title-row">
              <FileText size={14} className="section-icon" />
              <span className="section-label">SOURCE CODE</span>
            </div>
            <button
              type="button"
              className="copy-source-btn"
              onClick={handleCopyCode}
              title="Copy Source Code"
            >
              {copiedCode ? <Check size={13} /> : <Copy size={13} />}
              <span>{copiedCode ? 'Copied' : 'Copy'}</span>
            </button>
          </div>

          {sourceCode ? (
            <div className="code-viewer-container">
              <div className="code-lines-wrapper">
                {codeLines.map((line, idx) => (
                  <div key={idx} className="code-line-row">
                    <span className="code-line-number">{startLine + idx}</span>
                    <span className="code-line-text">{line || ' '}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="empty-source-card">
              <code>{data.signature || `def ${data.name || 'symbol'}():`}</code>
            </div>
          )}
        </div>

        {/* Action Button: Trace Execution */}
        <button
          type="button"
          className="trace-execution-btn"
          onClick={() => onTrace && onTrace(data.id || selected.id)}
        >
          <CornerDownRight size={15} />
          <span>Trace Downstream Execution →</span>
        </button>

        {/* Incoming Callers */}
        <div className="inspector-section">
          <div className="section-header-row">
            <span className="section-label">INCOMING CALLERS</span>
            <span className="section-count">({data.incoming_callers?.length || 0})</span>
          </div>
          {data.incoming_callers?.length ? (
            <div className="dependencies-list">
              {data.incoming_callers.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className="dependency-item"
                  onClick={() => onSelectSymbol && onSelectSymbol(c)}
                >
                  <span className={`kind-dot ${c.kind}`} />
                  <span className="dep-name">{c.label}</span>
                  <span className="dep-file">{c.file}</span>
                  <ChevronRight size={13} className="dep-arrow" />
                </button>
              ))}
            </div>
          ) : (
            <p className="empty-subtext">No direct incoming callers detected.</p>
          )}
        </div>

        {/* Outgoing Dependencies */}
        <div className="inspector-section">
          <div className="section-header-row">
            <span className="section-label">OUTGOING DEPENDENCIES</span>
            <span className="section-count">({data.outgoing_dependencies?.length || 0})</span>
          </div>
          {data.outgoing_dependencies?.length ? (
            <div className="dependencies-list">
              {data.outgoing_dependencies.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  className="dependency-item"
                  onClick={() => onSelectSymbol && onSelectSymbol(d)}
                >
                  <span className={`kind-dot ${d.kind}`} />
                  <span className="dep-name">{d.label}</span>
                  <span className="dep-edge-type">{d.type}</span>
                  <ChevronRight size={13} className="dep-arrow" />
                </button>
              ))}
            </div>
          ) : (
            <p className="empty-subtext">No outgoing calls or dependencies.</p>
          )}
        </div>

        {/* Git Blame & Commit History */}
        <div className="inspector-section">
          <div className="section-header-row">
            <span className="section-label">GIT BLAME & COMMITS</span>
            <GitCommit size={13} className="section-icon" />
          </div>
          {data.history?.length ? (
            <div className="history-timeline">
              {data.history.map((h, i) => (
                <div key={`${h.commit}-${i}`} className="history-item">
                  <div className="history-dot" />
                  <div className="history-content">
                    <div className="history-meta">
                      <span className="history-sha">{h.commit}</span>
                      <span className="history-author">{h.author}</span>
                      <span className="history-date">
                        {h.date ? new Date(h.date).toLocaleDateString() : ''}
                      </span>
                    </div>
                    <p className="history-msg">{h.message}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-subtext">No git blame history available for this line range.</p>
          )}
        </div>
      </div>
    </div>
  )
}
