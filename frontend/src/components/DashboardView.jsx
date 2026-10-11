import React, { useState, useEffect } from 'react'
import {
  GitBranch,
  Terminal,
  Compass,
  ArrowRight,
  Clock,
  Trash2,
  Sparkles,
  ExternalLink,
  Code2,
  Flame,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react'

const EXAMPLE_REPOS = [
  { name: 'fastapi/fastapi', branch: 'master', desc: 'Modern async Python API framework' },
  { name: 'pallets/flask', branch: 'main', desc: 'Python WSGI micro web framework' },
  { name: 'psf/requests', branch: 'main', desc: 'A simple, elegant HTTP library' },
  { name: 'encode/starlette', branch: 'master', desc: 'Lightweight ASGI framework' },
]

export default function DashboardView({
  onAnalyze,
  onOpenCached,
  loading = false,
  error = '',
}) {
  const [repoInput, setRepoInput] = useState('')
  const [branchInput, setBranchInput] = useState('main')
  const [recents, setRecents] = useState([])
  const [validationError, setValidationError] = useState('')

  // Load recents from localStorage
  useEffect(() => {
    try {
      const stored = localStorage.getItem('code_archaeologist_recents')
      if (stored) {
        setRecents(JSON.parse(stored))
      }
    } catch {
      // Ignore storage errors
    }
  }, [])

  const validateRepo = (value) => {
    const val = value.trim()
    if (!val) {
      setValidationError('Please enter a GitHub repository URL or owner/repo')
      return false
    }
    // Allow owner/repo or github url
    const isOwnerRepo = /^[\w.-]+\/[\w.-]+$/.test(val)
    const isGithubUrl = /^https?:\/\/(www\.)?github\.com\/[\w.-]+\/[\w.-]+(\.git)?\/?$/.test(val)
    if (!isOwnerRepo && !isGithubUrl) {
      setValidationError('Please enter a valid GitHub repo (e.g. owner/repo or https://github.com/owner/repo)')
      return false
    }
    setValidationError('')
    return true
  }

  const handleSubmit = (e) => {
    e?.preventDefault()
    if (!validateRepo(repoInput)) return
    onAnalyze(repoInput.trim(), branchInput.trim() || 'main')
  }

  const handleSelectExample = (ex) => {
    setRepoInput(ex.name)
    setBranchInput(ex.branch)
    setValidationError('')
  }

  const handleRemoveRecent = (repoId, e) => {
    e.stopPropagation()
    const updated = recents.filter((r) => r.repo_id !== repoId)
    setRecents(updated)
    localStorage.setItem('code_archaeologist_recents', JSON.stringify(updated))
  }

  const handleClearRecents = () => {
    setRecents([])
    localStorage.removeItem('code_archaeologist_recents')
  }

  return (
    <div className="dashboard-container">
      {/* Background Dot Grid Canvas */}
      <div className="dot-grid-canvas" />

      {/* Hero Content */}
      <div className="dashboard-hero">
        <div className="hero-pill-badge">
          <Sparkles size={13} className="hero-sparkle-icon" />
          <span>AST SYMBOL VISUALIZATION & GIT ARCHEOLOGY</span>
        </div>

        <h1 className="hero-title">
          Code <span className="hero-gradient-text">Archaeologist</span>
        </h1>
        <p className="hero-subtitle">
          Excavate unfamiliar Python repositories with interactive circular dependency graphs,
          file clustering, and commit-history grounded architectural context.
        </p>

        {/* Command Search Box */}
        <form onSubmit={handleSubmit} className="hero-command-card">
          <div className="command-input-row">
            <div className="repo-input-wrapper">
              <Terminal size={18} className="terminal-prefix-icon" />
              <input
                type="text"
                placeholder="github.com/owner/repo or owner/repo"
                value={repoInput}
                onChange={(e) => {
                  setRepoInput(e.target.value)
                  if (validationError) validateRepo(e.target.value)
                }}
                disabled={loading}
                className="repo-text-input"
                autoFocus
              />
            </div>

            <div className="branch-input-wrapper">
              <GitBranch size={15} className="branch-prefix-icon" />
              <input
                type="text"
                placeholder="branch (main)"
                value={branchInput}
                onChange={(e) => setBranchInput(e.target.value)}
                disabled={loading}
                className="branch-text-input"
              />
            </div>

            <button
              type="submit"
              disabled={loading || !repoInput.trim()}
              className="probe-trigger-btn"
            >
              {loading ? (
                <>
                  <span className="spinner-dot" />
                  <span>Excavating…</span>
                </>
              ) : (
                <>
                  <span>Archaeologize / Probe</span>
                  <ArrowRight size={15} />
                </>
              )}
            </button>
          </div>

          {(validationError || error) && (
            <div className="dashboard-error-banner">
              <AlertCircle size={15} />
              <span>{validationError || error}</span>
            </div>
          )}
        </form>

        {/* Quick Launch Examples */}
        <div className="examples-section">
          <span className="examples-label">Try popular repositories:</span>
          <div className="example-chips">
            {EXAMPLE_REPOS.map((ex) => (
              <button
                key={ex.name}
                type="button"
                className="example-chip"
                onClick={() => handleSelectExample(ex)}
              >
                <code>{ex.name}</code>
              </button>
            ))}
          </div>
        </div>

        {/* Recent Analyzed Repositories Section */}
        {recents.length > 0 && (
          <div className="recents-section">
            <div className="recents-header-row">
              <div className="recents-title-group">
                <Clock size={16} />
                <h3>Recent Analyzed Repositories</h3>
              </div>
              <button
                type="button"
                className="clear-recents-btn"
                onClick={handleClearRecents}
              >
                Clear all
              </button>
            </div>

            <div className="recents-grid">
              {recents.map((item) => (
                <div
                  key={item.repo_id || item.repo_name}
                  className="recent-card"
                  onClick={() => onOpenCached(item)}
                >
                  <div className="recent-card-top">
                    <span className="recent-repo-name">{item.repo_name}</span>
                    <button
                      type="button"
                      className="delete-recent-btn"
                      onClick={(e) => handleRemoveRecent(item.repo_id, e)}
                      title="Remove from recents"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>

                  <div className="recent-card-pills">
                    <span className="recent-pill language-pill">Python</span>
                    <span className="recent-pill branch-pill">
                      <GitBranch size={11} />
                      {item.branch || 'main'}
                    </span>
                    {item.num_files && (
                      <span className="recent-pill files-pill">
                        {item.num_files} files
                      </span>
                    )}
                  </div>

                  <div className="recent-card-footer">
                    <span className="recent-date">
                      {item.timestamp ? new Date(item.timestamp).toLocaleDateString() : 'Cached'}
                    </span>
                    <span className="quick-launch-link">
                      Open Workspace <ArrowRight size={12} />
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
