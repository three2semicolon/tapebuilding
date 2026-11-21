/**
 * DownloadView - enqueue a download (or sync) job. Split out of JobsView so
 * the download form lives on its own route.
 */

import { useState } from 'react'
import { api } from '@/services/api'

interface DownloadViewProps {
  onBack: () => void
}

export function DownloadView({ onBack }: DownloadViewProps) {
  const [url, setUrl] = useState('')
  const [organize, setOrganize] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [lastJobId, setLastJobId] = useState<string | null>(null)

  const handleCreateDownload = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return
    setSubmitting(true)
    try {
      const { id } = await api.createJob('download', url.trim(), organize ? '1' : '')
      setLastJobId(id)
      setUrl('')
    } catch (err) {
      alert(`Failed to start download: ${err}`)
    } finally {
      setSubmitting(false)
    }
  }

  const handleCreateSync = async () => {
    setSubmitting(true)
    try {
      const { id } = await api.syncPlaylists()
      setLastJobId(id)
    } catch (err) {
      alert(`Failed to start sync: ${err}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="app">
      <div className="page-header">
        <button className="btn small secondary" onClick={onBack}>
          ← back
        </button>
        <h2 style={{ margin: 0 }}>download</h2>
      </div>

      <div className="card">
        <h3>new download</h3>
        <form onSubmit={handleCreateDownload} style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <input
            id="download-url"
            placeholder="Spotify or YouTube URL (or search query)"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            style={{ flex: 1 }}
            disabled={submitting}
          />
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            <input
              type="checkbox"
              checked={organize}
              onChange={(e) => setOrganize(e.target.checked)}
              disabled={submitting}
            />
            organize into crate
          </label>
          <button
            className="btn"
            type="submit"
            disabled={submitting || !url.trim()}
          >
            {submitting ? 'starting…' : 'download'}
          </button>
        </form>

        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button
            className="btn secondary"
            onClick={handleCreateSync}
            disabled={submitting}
          >
            {submitting ? 'starting…' : 'sync playlists'}
          </button>
        </div>

        {lastJobId && (
          <div className="muted" style={{ marginBottom: 12 }}>
            job started: {lastJobId} — open Jobs to watch progress
          </div>
        )}

        <button className="btn secondary" onClick={onBack}>
          back
        </button>
      </div>
    </div>
  )
}
