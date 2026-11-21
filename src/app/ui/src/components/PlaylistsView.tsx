/**
 * PlaylistsView - playlist listing with cards, create/delete, and navigation.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Playlist } from '@/services/api'
import { PlaylistCard } from './PlaylistCard'

interface PlaylistsViewProps {
  onSelectPlaylist: (name: string) => void
}

export function PlaylistsView({ onSelectPlaylist }: PlaylistsViewProps) {
  const [newName, setNewName] = useState('')

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['playlists'],
    queryFn: api.listPlaylists,
  })

  const playlists: Playlist[] = data?.playlists ?? []

  const handleCreate = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!newName.trim()) return
    try {
      await api.createPlaylist(newName.trim())
      setNewName('')
      refetch()
    } catch (err) {
      alert(`Failed to create playlist: ${err}`)
    }
  }

  const handleDelete = async (name: string) => {
    if (!window.confirm(`Delete playlist "${name}"?`)) return
    try {
      await api.deletePlaylist(name)
      refetch()
    } catch (err) {
      alert(`Failed to delete playlist: ${err}`)
    }
  }

  if (isLoading) {
    return <div className="loading">loading playlists…</div>
  }

  if (error) {
    return (
      <div className="error-state">
        <div className="title">failed to load playlists</div>
        <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
          {String(error)}
        </div>
        <button className="btn" onClick={() => refetch()} style={{ marginTop: 10 }}>
          retry
        </button>
      </div>
    )
  }

  return (
    <div className="app">
      <div className="page-header">
        <h2>playlists</h2>
        <div className="page-actions">
          <button className="btn secondary" onClick={() => refetch()}>
            refresh
          </button>
        </div>
      </div>

      <div className="card">
        <h3>create playlist</h3>
        <form onSubmit={handleCreate} style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <input
            id="new-playlist"
            placeholder="playlist name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleCreate(e)}
            style={{ flex: 1 }}
          />
          <button className="btn" type="submit" disabled={!newName.trim()}>
            create
          </button>
        </form>
      </div>

      <div className="playlists-grid">
        {playlists.map((pl) => (
          <PlaylistCard
            key={pl.name}
            playlist={pl}
            onClick={onSelectPlaylist}
            onDelete={handleDelete}
          />
        ))}
        {playlists.length === 0 && (
          <div className="muted" style={{ gridColumn: '1 / -1', textAlign: 'center', padding: 24 }}>
            no playlists yet. create one above.
          </div>
        )}
      </div>
    </div>
  )
}
