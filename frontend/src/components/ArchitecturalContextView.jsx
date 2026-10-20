import React, { useState, useEffect, useRef } from 'react'
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
  MessageSquare,
  ArrowRight,
  Compass,
} from 'lucide-react'

export default function ArchitecturalContextView({
  repoId,
  contextMarkdown = '',
  onAskQuestion,
  onHighlightNodes,
  onJumpToSymbol,
}) {
  const [copied, setCopied] = useState(false)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [threads, setThreads] = useState([])
  const [error, setError] = useState('')
  const chatScrollRef = useRef(null)

  // Load persistent Q&A conversation history from SQLite database
  useEffect(() => {
    if (!repoId) return
    fetch(`/api/qa/${repoId}`)
      .then((res) => {
        if (!res.ok) throw new Error('Could not fetch Q&A history')
        return res.json()
      })
      .then((data) => {
        if (data.threads && data.threads.length > 0) {
          setThreads(data.threads)
        }
      })
      .catch((err) => {
        console.warn('Q&A history load error:', err)
      })
  }, [repoId])

  // Scroll to bottom of chat when new message arrives
  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight
    }
  }, [threads, asking])

  const handleCopy = () => {
    if (!contextMarkdown) return
    navigator.clipboard.writeText(contextMarkdown)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleAsk = async (e) => {
    e?.preventDefault()
    if (!question.trim() || !repoId || asking) return

    const currentQuestion = question.trim()
    setAsking(true)
    setError('')
    setQuestion('')

    const tempId = Date.now()
    const newThreadItem = {
      id: tempId,
      question: currentQuestion,
      answer: '',
      highlighted_ids: [],
      created_at: new Date().toISOString(),
      isStreaming: true,
    }

    setThreads((prev) => [...prev, newThreadItem])

    try {
      const res = await fetch(`/api/ask/stream/${repoId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: currentQuestion }),
      })

      if (!res.ok) {
        const errorText = await res.text()
        throw new Error(errorText || `Request failed with HTTP ${res.status}`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const event = JSON.parse(line)
            if (event.type === 'metadata') {
              if (event.highlighted_ids && event.highlighted_ids.length > 0) {
                setThreads((prev) =>
                  prev.map((t) =>
                    t.id === tempId ? { ...t, highlighted_ids: event.highlighted_ids } : t
                  )
                )
                if (onHighlightNodes) onHighlightNodes(event.highlighted_ids)
              }
            } else if (event.type === 'token') {
              setThreads((prev) =>
                prev.map((t) =>
                  t.id === tempId ? { ...t, answer: t.answer + event.delta } : t
                )
              )
            } else if (event.type === 'done') {
              setThreads((prev) =>
                prev.map((t) =>
                  t.id === tempId
                    ? {
                        ...t,
                        answer: event.full_answer || t.answer,
                        highlighted_ids: event.highlighted_ids || t.highlighted_ids,
                        isStreaming: false,
                      }
                    : t
                )
              )
            } else if (event.type === 'error') {
              throw new Error(event.detail || 'Streaming failed')
            }
          } catch (parseErr) {
            console.warn('Stream chunk parse error:', parseErr)
          }
        }
      }
    } catch (err) {
      setError(err.message)
      setThreads((prev) =>
        prev.map((t) =>
          t.id === tempId
            ? {
                ...t,
                answer: t.answer || '*(Failed to generate explanation. Please try again.)*',
                isStreaming: false,
              }
            : t
        )
      )
    } finally {
      setAsking(false)
      setThreads((prev) =>
        prev.map((t) => (t.id === tempId ? { ...t, isStreaming: false } : t))
      )
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

        {/* Right: Interactive Persistent Gemini Q&A */}
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

          {/* Persistent Multi-Turn Conversation Thread Feed */}
          <div className="qa-chat-history-feed" ref={chatScrollRef}>
            {threads.length === 0 && !asking && (
              <div className="qa-empty-thread-state">
                <MessageSquare size={24} className="qa-empty-icon" />
                <p>No questions asked yet for this repository.</p>
                <span className="qa-example-hint">
                  Try: "Why does authentication parse tokens this way?" or "Explain the request handling lifecycle."
                </span>
              </div>
            )}

            {threads.map((item, idx) => (
              <div key={item.id || idx} className="qa-thread-message-pair">
                {/* User Question Bubble */}
                <div className="qa-user-bubble">
                  <div className="qa-bubble-header">
                    <span className="user-label">You</span>
                    {item.created_at && (
                      <span className="qa-time">{new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                    )}
                  </div>
                  <p className="user-question-text">{item.question}</p>
                </div>

                {/* Gemini Answer Card */}
                <div className="qa-answer-card">
                  <div className="qa-answer-header">
                    <Sparkles size={14} className="ai-star-icon" />
                    <span>GEMINI EXPLANATION</span>
                    {item.isStreaming && (
                      <span className="qa-streaming-pill">
                        <span className="pulse-dot" /> Streaming
                      </span>
                    )}
                  </div>
                  <div className="qa-answer-body markdown-content">
                    {item.answer ? (
                      <>
                        <ReactMarkdown>{item.answer}</ReactMarkdown>
                        {item.isStreaming && <span className="streaming-cursor" />}
                      </>
                    ) : (
                      <div className="qa-shimmer-loading">
                        <Cpu size={14} className="spinning" />
                        <span>Retrieving AST symbols, traces & Git history...</span>
                      </div>
                    )}
                  </div>

                  {item.highlighted_ids && item.highlighted_ids.length > 0 && (
                    <div className="qa-citations-section">
                      <span className="citations-label">Grounded in symbols (click to inspect on graph):</span>
                      <div className="citations-chips">
                        {item.highlighted_ids.map((symId) => (
                          <button
                            type="button"
                            key={symId}
                            className="citation-chip clickable"
                            onClick={() => onJumpToSymbol && onJumpToSymbol(symId)}
                            title={`Inspect ${symId} on the graph canvas`}
                          >
                            <Compass size={11} className="chip-compass-icon" />
                            <span>{symId.split('::').pop().replace('cls_', '').replace('fn_', '')}</span>
                            <ArrowRight size={10} className="chip-arrow-icon" />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {asking && !threads.some((t) => t.isStreaming) && (
              <div className="qa-reasoning-indicator">
                <Cpu size={15} className="spinning" />
                <span>Gemini is analyzing AST symbols, call traces, and Git commit history…</span>
              </div>
            )}
          </div>

          {error && <div className="qa-error-alert">{error}</div>}

          {/* Sticky Bottom Question Form */}
          <form onSubmit={handleAsk} className="qa-input-form sticky-form">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask a 'why' or architectural question (e.g. Why was this validation logic added?)..."
              rows={2}
              className="qa-textarea"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleAsk()
                }
              }}
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
        </div>
      </div>
    </div>
  )
}
