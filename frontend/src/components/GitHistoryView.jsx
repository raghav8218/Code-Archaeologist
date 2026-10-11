import React, { useState, useMemo } from 'react'
import {
  GitCommit,
  ExternalLink,
  Flame,
  Search,
  User,
  Calendar,
  FileText,
  Filter,
} from 'lucide-react'

export default function GitHistoryView({ commits = [], fileChangeFreq = {}, repoUrl = '' }) {
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedFileFilter, setSelectedFileFilter] = useState(null)

  // Rank hotspot files by change frequency
  const rankedHotspots = useMemo(() => {
    return Object.entries(fileChangeFreq)
      .filter(([file]) => file && file !== 'external' && file !== 'misc')
      .sort((a, b) => b[1] - a[1])
  }, [fileChangeFreq])

  const maxFreq = rankedHotspots.length ? rankedHotspots[0][1] : 1

  // Filter commits
  const filteredCommits = useMemo(() => {
    return commits.filter((c) => {
      const matchesSearch =
        !searchTerm.trim() ||
        c.message.toLowerCase().includes(searchTerm.toLowerCase()) ||
        c.author.toLowerCase().includes(searchTerm.toLowerCase()) ||
        c.hash.toLowerCase().includes(searchTerm.toLowerCase())
      return matchesSearch
    })
  }, [commits, searchTerm])

  return (
    <div className="git-history-view">
      <div className="git-history-layout">
        {/* Left / Main: Commit Timeline */}
        <div className="commits-timeline-column">
          <div className="commits-header-bar">
            <div className="commits-search-box">
              <Search size={14} className="search-icon" />
              <input
                type="text"
                placeholder="Search commit messages, authors, or hashes..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="commits-search-input"
              />
            </div>
            <span className="commits-count-badge">
              {filteredCommits.length} {filteredCommits.length === 1 ? 'commit' : 'commits'}
            </span>
          </div>

          <div className="commits-list">
            {filteredCommits.length > 0 ? (
              filteredCommits.map((c) => (
                <div key={c.hexsha || c.hash} className="commit-card">
                  <div className="commit-card-header">
                    <div className="commit-sha-row">
                      <GitCommit size={14} className="commit-icon" />
                      {c.url ? (
                        <a
                          href={c.url}
                          target="_blank"
                          rel="noreferrer"
                          className="commit-sha-link"
                          title="Open commit on GitHub"
                        >
                          <code>{c.hash}</code>
                          <ExternalLink size={12} />
                        </a>
                      ) : (
                        <code className="commit-sha-code">{c.hash}</code>
                      )}
                    </div>
                    <span className="commit-date">
                      <Calendar size={12} />
                      {c.relative_date || (c.date ? new Date(c.date).toLocaleDateString() : '')}
                    </span>
                  </div>

                  <p className="commit-message">{c.message}</p>

                  <div className="commit-card-footer">
                    <div className="commit-author">
                      <User size={12} />
                      <span>{c.author}</span>
                    </div>
                    {c.files_changed > 0 && (
                      <span className="commit-files-changed">
                        {c.files_changed} {c.files_changed === 1 ? 'file' : 'files'} changed
                      </span>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-commits-state">
                <p>No commits match your search query.</p>
              </div>
            )}
          </div>
        </div>

        {/* Right: Churn Hotspots Breakdown */}
        <div className="churn-hotspots-column">
          <div className="churn-header">
            <Flame size={16} className="flame-icon" />
            <h4>File Churn Hotspots</h4>
          </div>
          <p className="churn-description">
            Files with the highest modification frequency in git history.
          </p>

          <div className="churn-list">
            {rankedHotspots.slice(0, 15).map(([file, freq]) => {
              const percentage = Math.max(8, Math.round((freq / maxFreq) * 100))
              const isSelected = selectedFileFilter === file

              return (
                <div
                  key={file}
                  className={`churn-item ${isSelected ? 'selected' : ''}`}
                  onClick={() => setSelectedFileFilter(isSelected ? null : file)}
                >
                  <div className="churn-item-meta">
                    <span className="churn-filename" title={file}>
                      {file}
                    </span>
                    <span className="churn-badge">
                      {freq} {freq === 1 ? 'commit' : 'commits'}
                    </span>
                  </div>
                  <div className="churn-bar-track">
                    <div
                      className="churn-bar-fill"
                      style={{
                        width: `${percentage}%`,
                        backgroundColor: freq > maxFreq * 0.6 ? '#EF4444' : '#F59E0B',
                      }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
