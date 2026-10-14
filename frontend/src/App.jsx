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
  const [progress, setProgress] = useState({
    active: false,
    step: 0,
    stage: '',
    message: '',
    percent: 0,
    logs: [],
  })

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

  // Analyze repo action with real-time SSE progress
  const handleAnalyze = async (repoUrl, branch = '') => {
    setLoading(true)
    setError('')
    setHighlightedIds([])
    setProgress({
      active: true,
      step: 1,
      stage: 'cloning',
      message: 'Connecting to GitHub repository...',
      percent: 10,
      logs: ['Initiating archaeological analysis probe...'],
    })

    try {
      const res = await fetch('/api/analyze/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl, branch: branch || null }),
      })

      if (!res.ok) {
        let errDetail = 'Analysis request failed.'
        try {
          const errData = await res.json()
          errDetail = errData.detail || errDetail
        } catch {
          // ignore
        }
        throw new Error(errDetail)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let finalData = null

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const msg = JSON.parse(line.trim())
            if (msg.type === 'progress') {
              setProgress((prev) => ({
                active: true,
                step: msg.step,
                stage: msg.stage,
                message: msg.message,
                percent: msg.percent,
                logs: [...prev.logs.slice(-12), msg.message],
              }))
            } else if (msg.type === 'complete') {
              finalData = msg.result
            } else if (msg.type === 'error') {
              throw new Error(msg.detail || 'Analysis pipeline error')
            }
          } catch (pe) {
            if (pe.message && !pe.message.includes('JSON')) {
              throw pe
            }
          }
        }
      }

      if (!finalData) {
        throw new Error('Analysis completed without receiving repository data.')
      }

      setRepoData(finalData)

      // Store in localStorage safely
      try {
        localStorage.setItem('code_archaeologist_active_repo', JSON.stringify(finalData))

        // Update recents list
        const recentsRaw = localStorage.getItem('code_archaeologist_recents')
        const recents = recentsRaw ? JSON.parse(recentsRaw) : []
        const newEntry = {
          repo_id: finalData.repo_id,
          repo_name: finalData.repo_name,
          repo_url: finalData.repo_url,
          branch: finalData.branch,
          num_files: finalData.num_files,
          num_functions: finalData.num_functions,
          timestamp: new Date().toISOString(),
          cachedData: finalData,
        }
        const filtered = recents.filter((r) => r.repo_name !== finalData.repo_name)
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
      setProgress((prev) => ({ ...prev, active: false }))
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
          progress={progress}
          error={error}
        />
      )}
    </div>
  )
}
