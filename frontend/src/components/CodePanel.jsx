import React, { useEffect, useState } from 'react'

export default function CodePanel({ repoId, selected, onTrace }) {
  const [details, setDetails] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!selected) return
    setLoading(true)
    setDetails(null)
    fetch(`/api/function/${repoId}?id=${encodeURIComponent(selected.id)}`)
      .then((r) => r.json())
      .then(setDetails)
      .finally(() => setLoading(false))
  }, [selected, repoId])

  if (!selected) {
    return (
      <div className="panel-empty">
        <p>Select a function on the graph to inspect its source and history.</p>
      </div>
    )
  }

  return (
    <div className="code-panel">
      <div className="code-panel-header">
        <span className="eyebrow">FUNCTION</span>
        <h3>{selected.qualified_name}</h3>
        <span className="muted small">
          {selected.file}:{selected.start_line}
        </span>
        <button className="trace-btn" onClick={() => onTrace(selected.id)}>
          Trace from here →
        </button>
      </div>

      {loading && <p className="muted">Loading…</p>}

      {details && (
        <>
          {details.change_frequency > 0 && (
            <div className="hotspot-badge">
              <span className="hotspot-dot" />
              Changed in {details.change_frequency} commit{details.change_frequency === 1 ? "" : "s"} — file-level history
            </div>
          )}

          <pre className="code-block">
            <code>{details.source}</code>
          </pre>

          <div className="history">
            <span className="eyebrow">HISTORY</span>
            {details.history?.length ? (
              <ul>
                {details.history.map((h) => (
                  <li key={h.commit}>
                    <span className="commit">{h.commit}</span>
                    <span className="author">{h.author}</span>
                    <span className="msg">{h.message}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted small">No blame history found for this file.</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
