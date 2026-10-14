import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import {
  FileText,
  Copy,
  Check,
  Sparkles,
  Send,
  HelpCircle,
  Cpu,
  Layers,
} from 'lucide-react'

export default function ArchitecturalContextView({
  repoId,
  contextMarkdown = '',
  onAskQuestion,
  onHighlightNodes,
}) {
  const [copied, setCopied] = useState(false)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState('')
  const [highlightedSymbols, setHighlightedSymbols] = useState([])
  const [error, setError] = useState('')

  const handleCopy = () => {
    if (!contextMarkdown) return
    navigator.clipboard.writeText(contextMarkdown)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleAsk = async (e) => {
    e?.preventDefault()
    if (!question.trim() || !repoId || asking) return

    setAsking(true)
    setError('')
    setAnswer('')

    try {
      const res = await fetch(`/api/ask/${repoId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })

      let data = {}
      const responseText = await res.text()
      try {
        data = JSON.parse(responseText)
      } catch (jsonErr) {
        throw new Error(responseText || `Request failed with HTTP ${res.status}`)
      }

      if (!res.ok) throw new Error(data.detail || 'Failed to get answer from Gemini')

      setAnswer(data.answer)
      setHighlightedSymbols(data.highlighted_ids || [])
      if (onHighlightNodes && data.highlighted_ids) {
        onHighlightNodes(data.highlighted_ids)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="architectural-context-view">
      <div className="context-split-layout">
        {/* Left: Markdown Context Summary */}
        <div className="context-markdown-column">
          <div className="column-top-bar">
            <div className="column-title-group">
              <Layers size={16} className="title-icon" />
              <h3>LLM Architectural Context</h3>
            </div>
            <button
              type="button"
              className="copy-context-btn"
              onClick={handleCopy}
              title="Copy markdown prompt context for LLMs"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
              <span>{copied ? 'Copied to Clipboard' : 'Copy for LLM'}</span>
            </button>
          </div>

          <div className="markdown-content-box">
            <pre className="markdown-text">
              <code>{contextMarkdown || '# Generating architectural context...'}</code>
            </pre>
          </div>
        </div>

        {/* Right: Interactive Gemini Q&A */}
        <div className="context-qa-column">
          <div className="column-top-bar">
            <div className="column-title-group">
              <Sparkles size={16} className="title-icon-ai" />
              <h3>Grounded Gemini Q&A</h3>
            </div>
            <span className="qa-badge">Code + Git History</span>
          </div>

          <p className="qa-subtext">
            Ask architectural or "why" questions. Gemini retrieves relevant AST symbols and Git blame commits to ground its explanation.
          </p>

          <form onSubmit={handleAsk} className="qa-input-form">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. Why does authentication handle tokens this way? How do routes interact with the parser?"
              rows={3}
              className="qa-textarea"
            />
            <button
              type="submit"
              disabled={asking || !question.trim()}
              className="qa-submit-btn"
            >
              {asking ? (
                <>
                  <Cpu size={14} className="spinning" />
                  <span>Reasoning…</span>
                </>
              ) : (
                <>
                  <Send size={14} />
                  <span>Ask Gemini</span>
                </>
              )}
            </button>
          </form>

          {error && <div className="qa-error-alert">{error}</div>}

          {answer && (
            <div className="qa-answer-card">
              <div className="qa-answer-header">
                <Sparkles size={14} className="ai-star-icon" />
                <span>EXPLANATION</span>
              </div>
              <div className="qa-answer-body markdown-content">
                <ReactMarkdown>{answer}</ReactMarkdown>
              </div>

              {highlightedSymbols.length > 0 && (
                <div className="qa-citations-section">
                  <span className="citations-label">Grounded in symbols:</span>
                  <div className="citations-chips">
                    {highlightedSymbols.map((symId) => (
                      <span key={symId} className="citation-chip">
                        {symId.split('::').pop()}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
