import React, { useState } from 'react'
import {
  ArrowLeft,
  GitBranch,
  Network,
  GitCommit,
  Layers,
  Sidebar,
  ExternalLink,
  ChevronRight,
  Code2,
  FileCode,
  Flame,
} from 'lucide-react'

import GraphView from './GraphView.jsx'
import GitHistoryView from './GitHistoryView.jsx'
import ArchitecturalContextView from './ArchitecturalContextView.jsx'
import NodeInspector from './NodeInspector.jsx'

export default function WorkspaceView({
  repoData,
  onBackToDashboard,
  onTrace,
  highlightedIds = [],
  onSetHighlightedIds,
}) {
  const [activeTab, setActiveTab] = useState('graph') // 'graph' | 'git' | 'context'
  const [selectedNode, setSelectedNode] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const {
    repo_id,
    repo_name,
    repo_url,
    branch = 'main',
    graph = { nodes: [], edges: [] },
    num_files = 0,
    num_functions = 0,
    num_classes = 0,
    commits = [],
    architectural_context = '',
  } = repoData || {}

  // File change frequencies mapped from nodes
  const fileChangeFreq = repoData?.file_change_freq || {}
  if (!Object.keys(fileChangeFreq).length && graph.nodes) {
    graph.nodes.forEach((n) => {
      if (n.file && n.change_frequency) {
        fileChangeFreq[n.file] = Math.max(fileChangeFreq[n.file] || 0, n.change_frequency)
      }
    })
  }

  const handleSelectSymbol = (symbol) => {
    setSelectedNode(symbol)
    setSidebarOpen(true)
  }

  return (
    <div className="workspace-container">
      {/* Top Header Bar */}
      <header className="workspace-header">
        <div className="header-left-group">
          <button
            type="button"
            className="header-back-btn"
            onClick={onBackToDashboard}
            title="Return to Dashboard"
          >
            <ArrowLeft size={16} />
            <span>Dashboard</span>
          </button>

          <span className="header-divider">/</span>

          {/* Repo Breadcrumb */}
          <div className="repo-breadcrumb">
            <span className="breadcrumb-repo-name">{repo_name || 'Repository'}</span>
            {repo_url && (
              <a
                href={repo_url}
                target="_blank"
                rel="noreferrer"
                className="repo-external-link"
                title="View on GitHub"
              >
                <ExternalLink size={13} />
              </a>
            )}
          </div>

          {/* Branch Pill */}
          <div className="header-branch-pill">
            <GitBranch size={13} />
            <span>{branch}</span>
          </div>

          {/* Quick Stats Pill */}
          <div className="header-stats-pill">
            <span>{num_files} files</span>
            <span className="stats-dot">·</span>
            <span>{num_classes} classes</span>
            <span className="stats-dot">·</span>
            <span>{num_functions} functions</span>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="workspace-tabs">
          <button
            type="button"
            className={`workspace-tab-btn ${activeTab === 'graph' ? 'active' : ''}`}
            onClick={() => setActiveTab('graph')}
          >
            <Network size={15} />
            <span>Graph Explorer</span>
          </button>

          <button
            type="button"
            className={`workspace-tab-btn ${activeTab === 'git' ? 'active' : ''}`}
            onClick={() => setActiveTab('git')}
          >
            <GitCommit size={15} />
            <span>Git History & Churn</span>
          </button>

          <button
            type="button"
            className={`workspace-tab-btn ${activeTab === 'context' ? 'active' : ''}`}
            onClick={() => setActiveTab('context')}
          >
            <Layers size={15} />
            <span>Architectural Context</span>
          </button>
        </div>

        {/* Right Header Action: Inspector Toggle */}
        <div className="header-right-group">
          <button
            type="button"
            className={`sidebar-toggle-btn ${sidebarOpen ? 'active' : ''}`}
            onClick={() => setSidebarOpen((prev) => !prev)}
            title="Toggle Node Inspector"
          >
            <Sidebar size={15} />
            <span>Inspector</span>
          </button>
        </div>
      </header>

      {/* Main Workspace Workspace Split Layout */}
      <div className="workspace-main-split">
        {/* Main Tab Content */}
        <main className="workspace-content-canvas">
          {activeTab === 'graph' && (
            <GraphView
              rawNodes={graph.nodes}
              rawEdges={graph.edges}
              highlightedIds={highlightedIds}
              selectedNode={selectedNode}
              onNodeClick={handleSelectSymbol}
            />
          )}

          {activeTab === 'git' && (
            <GitHistoryView
              commits={commits}
              fileChangeFreq={fileChangeFreq}
              repoUrl={repo_url}
            />
          )}

          {activeTab === 'context' && (
            <ArchitecturalContextView
              repoId={repo_id}
              contextMarkdown={architectural_context}
              onHighlightNodes={onSetHighlightedIds}
            />
          )}
        </main>

        {/* Resizable / Collapsible Right Inspector Sidebar */}
        {sidebarOpen && (
          <aside className="workspace-inspector-sidebar">
            <NodeInspector
              repoId={repo_id}
              selected={selectedNode}
              onClose={() => setSidebarOpen(false)}
              onTrace={onTrace}
              onSelectSymbol={handleSelectSymbol}
            />
          </aside>
        )}
      </div>
    </div>
  )
}
