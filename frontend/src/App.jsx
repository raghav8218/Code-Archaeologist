import React, { useState } from 'react'
import GraphView from './components/GraphView.jsx'
import CodePanel from './components/CodePanel.jsx'

export default function App() {
  const [repoUrl, setRepoUrl] = useState('')
  const [repoId, setRepoId] = useState(null)
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [meta, setMeta] = useState(null)
  const [selected, setSelected] = useState(null)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [highlighted, setHighlighted] = useState([])
  const [loading, setLoading] = useState(false)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState('')

  async function analyze() {
    setError('')
    setLoading(true)
    setAnswer('')
    setHighlighted([])
    setSelected(null)
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to analyze repo')
      setRepoId(data.repo_id)
      setGraph(data.graph)
      setMeta({ files: data.num_files, functions: data.num_functions })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function ask() {
    if (!question.trim() || !repoId) return
    setAsking(true)
    setAnswer('')
    setError('')
    try {
      const res = await fetch(`/api/ask/${repoId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to get answer')
      setAnswer(data.answer)
      setHighlighted(data.highlighted_ids)
    } catch (e) {
      setError(e.message)
    } finally {
      setAsking(false)
    }
  }

  async function trace(startId) {
    if (!repoId) return
    const res = await fetch(`/api/trace/${repoId}?start_id=${encodeURIComponent(startId)}`)
    const data = await res.json()
    setHighlighted(data.nodes)
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="eyebrow">CODE ARCHAEOLOGIST</span>
          <h1>Dig into any repo</h1>
        </div>

        <div className="field">
          <label>GitHub repository URL</label>
          <input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/owner/small-python-repo"
          />
          <button onClick={analyze} disabled={loading || !repoUrl}>
            {loading ? 'Excavating…' : 'Analyze repo'}
          </button>
        </div>

        {error && <p className="error">{error}</p>}

        {meta && (
          <p className="muted small">
            {meta.files} files · {meta.functions} functions parsed
          </p>
        )}

        {repoId && (
          <p className="muted small hotspot-legend">
            <span className="hotspot-dot" /> Thicker red border = frequently changed (git history)
          </p>
        )}

        {repoId && (
          <div className="field">
            <label>Ask about this codebase</label>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="How does authentication work?"
              rows={3}
            />
            <button onClick={ask} disabled={asking || !question.trim()}>
              {asking ? 'Thinking…' : 'Ask'}
            </button>
          </div>
        )}

        {answer && (
          <div className="answer">
            <span className="eyebrow">ANSWER</span>
            <p>{answer}</p>
          </div>
        )}
      </aside>

      <main className="canvas">
        {graph.nodes.length > 0 ? (
          <GraphView
            rawNodes={graph.nodes}
            rawEdges={graph.edges}
            highlightedIds={highlighted}
            onNodeClick={setSelected}
          />
        ) : (
          <div className="canvas-empty">
            <p>Paste a small Python repo URL and hit "Analyze repo" to see its architecture.</p>
          </div>
        )}
      </main>

      <aside className="detail">
        <CodePanel repoId={repoId} selected={selected} onTrace={trace} />
      </aside>
    </div>
  )
}
