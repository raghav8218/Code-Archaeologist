import React, { useState, useEffect } from 'react'
import DashboardView from './components/DashboardView.jsx'
import WorkspaceView from './components/WorkspaceView.jsx'

export default function App() {
  const [currentRoute, setCurrentRoute] = useState(
    window.location.pathname.startsWith('/workspace') ? '/workspace' : '/'
  )
  const [repoData, setRepoData] = useState(null)
  const [highlightedIds, setHighlightedIds] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Sync route changes with browser history
  useEffect(() => {
    const handlePopState = () => {
      const path = window.location.pathname.startsWith('/workspace') ? '/workspace' : '/'
      setCurrentRoute(path)
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  // Restore active repo from localStorage on initial load if on /workspace
  useEffect(() => {
    if (!repoData) {
      try {
        const storedCurrent = localStorage.getItem('code_archaeologist_active_repo')
        if (storedCurrent) {
          const parsed = JSON.parse(storedCurrent)
          setRepoData(parsed)
        } else if (currentRoute === '/workspace') {
          // If no active repo is found, return to dashboard
          navigateTo('/')
        }
      } catch {
        // Ignore JSON error
      }
    }
  }, [currentRoute, repoData])

  const navigateTo = (path) => {
    setCurrentRoute(path)
    if (window.location.pathname !== path) {
      window.history.pushState({}, '', path)
    }
  }

  // Analyze repo action
  const handleAnalyze = async (repoUrl, branch = 'main') => {
    setLoading(true)
    setError('')
    setHighlightedIds([])

    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl, branch }),
      })

      const data = await res.json()
      if (!res.ok) {
        throw new Error(data.detail || 'Analysis failed. Please verify the repo URL and branch.')
      }

      setRepoData(data)

      // Store in localStorage
      try {
        localStorage.setItem('code_archaeologist_active_repo', JSON.stringify(data))

        // Update recents list
        const recentsRaw = localStorage.getItem('code_archaeologist_recents')
        const recents = recentsRaw ? JSON.parse(recentsRaw) : []
        const newEntry = {
          repo_id: data.repo_id,
          repo_name: data.repo_name,
          repo_url: data.repo_url,
          branch: data.branch,
          num_files: data.num_files,
          num_functions: data.num_functions,
          timestamp: new Date().toISOString(),
          cachedData: data,
        }
        const filtered = recents.filter((r) => r.repo_name !== data.repo_name)
        const updatedRecents = [newEntry, ...filtered].slice(0, 8)
        localStorage.setItem('code_archaeologist_recents', JSON.stringify(updatedRecents))
      } catch (e) {
        console.warn('LocalStorage save failed:', e)
      }

      // Route smoothly to /workspace
      navigateTo('/workspace')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Open cached repo from recents
  const handleOpenCached = (recentItem) => {
    if (recentItem.cachedData) {
      setRepoData(recentItem.cachedData)
      localStorage.setItem('code_archaeologist_active_repo', JSON.stringify(recentItem.cachedData))
      navigateTo('/workspace')
    } else {
      handleAnalyze(recentItem.repo_url || recentItem.repo_name, recentItem.branch || 'main')
    }
  }

  // Downstream BFS tracing
  const handleTrace = async (startId) => {
    if (!repoData?.repo_id || !startId) return
    try {
      const res = await fetch(
        `/api/trace/${repoData.repo_id}?start_id=${encodeURIComponent(startId)}`
      )
      if (!res.ok) throw new Error('Trace failed')
      const data = await res.json()
      setHighlightedIds(data.nodes || [])
    } catch (e) {
      console.error(e)
    }
  }

  return (
    <div className="code-archaeologist-root">
      {currentRoute === '/workspace' && repoData ? (
        <WorkspaceView
          repoData={repoData}
          onBackToDashboard={() => navigateTo('/')}
          onTrace={handleTrace}
          highlightedIds={highlightedIds}
          onSetHighlightedIds={setHighlightedIds}
        />
      ) : (
        <DashboardView
          onAnalyze={handleAnalyze}
          onOpenCached={handleOpenCached}
          loading={loading}
          error={error}
        />
      )}
    </div>
  )
}
