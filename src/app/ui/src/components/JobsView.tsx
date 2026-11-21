/**
 * JobsView - background job list: enqueue, poll progress, show logs, delete.
 * Polls /api/jobs every 2 seconds while a job is running.
 */

import { useQuery, useState } from '@tanstack/react-query'
import { api, type Job } from '@/services/api'
import { useInterval } from '@/utils/useInterval'

interface JobsViewProps {
  onRefresh?: () => void
}

export function JobsView({ onRefresh }: JobsViewProps) {

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['jobs'],
    queryFn: api.listJobs,
  })

  const [toast, setToast] = useState<{ type: 'ok' | 'error'; msg: string } | null>(null)
  const [expandedJob, setExpandedJob] = useState<string | null>(null)

  const jobs: Job[] = data?.jobs ?? []

  const running = jobs.some((j) => j.state === 'queued' || j.state === 'running')
  const justFinished = jobs.some((j) => j.state === 'ok' || j.state === 'error')

  // poll every 2s while a job is running
  useInterval(() => {
    refetch()
  }, running ? 2000 : 0)

  // show a toast when a job lands in a terminal state
  if (justFinished && toast === null) {
    const errJob = jobs.find((j) => j.state === 'error')
    if (errJob) {
      setToast({ type: 'error', msg: `${errJob.type}: ${errJob.error ?? 'failed'}` })
    } else {
      setToast({ type: 'ok', msg: 'job finished' })
    }
  }

  const handleCreateDownload = async (url: string, organize: boolean) => {
    try {
      await api.createJob('download', url, organize ? '1' : '')
      refetch()
    } catch (err) {
      alert(`Failed to start download: ${err}`)
    }
  }

  const handleCreateSync = async () => {
    try {
      await api.syncPlaylists()
      refetch()
    } catch (err) {
      alert(`Failed to start sync: ${err}`)
    }
  }

  const handleDelete = async (jobId: string) => {
    try {
      await api.deleteJob(jobId)
      refetch()
    } catch (err) {
      alert(`Failed to delete job: ${err}`)
    }
  }

  if (isLoading) {
    return <div className="loading">loading jobs…</div>
  }

  if (error) {
    return (
      <div className="error-state">
        <div className="title">failed to load jobs</div>
        <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>{String(error)}</div>
        <button className="btn" onClick={() => refetch()} style={{ marginTop: 10 }}>
          retry
        </button>
      </div>
    )
  }

  return (
    <div className="app">
      {toast && (
        <div
          className="card"
          style={{
            border: toast.type === 'error' ? '3px solid var(--text-dark)' : '3px solid #6f9a5f',
            position: 'fixed',
            top: 12,
            right: 12,
            minWidth: 260,
            zIndex: 50,
            opacity: 0.95,
          }}
          onClick={() => setToast(null)}
        >
          <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.08em, marginBottom: 4 }}>
            {toast.type === 'error' ? 'job error' : 'job finished'}
          </div>
          <div style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{toast.msg}</div>
          <div style={{ fontSize: 10, color: 'var(--outline-soft)', marginTop: 6 }}>click to dismiss</div>
        </div>
      )}
      <div className="page-header">
        <h2>jobs</h2>
        <div className="page-actions">
          <button className="btn secondary" onClick={() => refetch()}>
            refresh
          </button>
          <button className="btn secondary" onClick={handleCreateSync}>
            sync playlists
          </button>
        </div>
      </div>

      <div className="card">
        <h3>new download</h3>
        <div className="download-form">
          <input
            id="download-url"
            placeholder="Spotify or YouTube URL (or search query)"
            style={{ flex: 1 }}
          />
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            <input type="checkbox" id="download-organize" />
            organize into crate
          </label>
          <button
            className="btn"
            onClick={() => {
              const input = document.getElementById('download-url') as HTMLInputElement | null
              const organize = document.getElementById('download-organize') as HTMLInputElement | null
              if (!input || !input.value) return
              handleCreateDownload(input.value, organize?.checked ?? false)
              input.value = ''
            }}
          >
            download
          </button>
        </div>
      </div>

      <div className="card">
        <h3>{jobs.length} job{jobs.length !== 1 ? 's' : ''}</h3>
        {jobs.length === 0 && (
          <div className="muted" style={{ textAlign: 'center', padding: 24 }}>
            no jobs yet.
          </div>
        )}
        <table className="tight">
          <thead>
            <tr>
              <th>type</th>
              <th className="numeric">state</th>
              <th className="numeric">progress</th>
              <th>target</th>
              <th className="numeric">created</th>
              <th style={{ width: 60 }}></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td style={{ textTransform: 'uppercase', fontSize: 12 }}>{job.type}</td>
                <td className="numeric">
                  <span className={`tag ${job.state === 'ok' ? 'ok' : job.state === 'error' ? 'bad' : 'warn'}`}>
                    {job.state}
                  </span>
                </td>
                <td className="numeric">
                  {job.progress.pct}%
                </td>
                <td style={{ fontSize: 12, color: 'var(--outline-soft)' }}>{job.meta.target || '–'}</td>
                <td className="numeric" style={{ fontSize: 12 }}>
                  {new Date(job.created_at * 1000).toLocaleTimeString()}
                </td>
                <td className="numeric">
                  <button
                    className="btn small danger"
                    onClick={() => handleDelete(job.id)}
                    disabled={job.state === 'running'}
                  >
                    delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* job detail: logs for running and finished jobs (expanded on click) */}
        <div className="card" style={{ marginTop: 14 }}>
          <h3>job log</h3>
          <div className="job-log">
            {[...jobs].reverse().map((job) => {
              const isOpen = expandedJob === job.id
              const terminal = job.state === 'ok' || job.state === 'error'
              const show = job.state === 'queued' || job.state === 'running' || terminal
              if (!show) return null
              return (
                <div key={job.id} className="job-log-block">
                  <div
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: 12,
                      marginBottom: 6,
                      cursor: 'pointer',
                    }}
                    onClick={() => setExpandedJob(isOpen ? null : job.id)}
                  >
                    {job.type} · {job.state} {isOpen ? '▾' : '▸'}
                  </div>
                  {isOpen && (
                    <>
                      <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', margin: 0 }}>
                        {job.log.join('\n')}
                      </pre>
                      {job.error && (
                        <div
                          style={{
                            color: '#8a4a6b',
                            marginTop: 6,
                            fontSize: 11,
                            borderTop: '1px solid var(--container-light)',
                            paddingTop: 6,
                          }}
                        >
                          error: {job.error}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {onRefresh && (
          <button className="btn secondary" style={{ marginTop: 12 }} onClick={onRefresh}>
            back
          </button>
        )}
      </div>
    </div>
  )
}
