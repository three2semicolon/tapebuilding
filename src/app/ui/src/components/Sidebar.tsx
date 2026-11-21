/**
 * Sidebar - left navigation with playlist list.
 */

import { useState } from 'react'
import { api, type Playlist } from '@/services/api'
import { PlaylistCard } from './PlaylistCard'
import { useSelectionCount } from '@/store/useSelectionStore'

interface SidebarProps {
  view: 'library' | 'playlists' | 'detail' | 'jobs' | 'download'
  playlists: Playlist[]
  selectedPlaylist: string | null
  onViewChange: (view: 'library' | 'playlists' | 'detail' | 'jobs' | 'download') => void
  onSelectPlaylist: (name: string) => void
}

export function Sidebar({
  view,
  playlists,
  selectedPlaylist,
  onViewChange,
  onSelectPlaylist,
}: SidebarProps) {
  const [newPlaylistName, setNewPlaylistName] = useState('')
  const selectionCount = useSelectionCount()

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">tapedeck</div>
        <div className="sidebar-tagline">the crate</div>
      </div>

      <nav className="sidebar-nav">
        <button
          className={`sidebar-nav-btn ${view === 'library' ? 'active' : ''}`}
          onClick={() => onViewChange('library')}
        >
          library
        </button>
        <button
          className={`sidebar-nav-btn ${view === 'playlists' ? 'active' : ''}`}
          onClick={() => onViewChange('playlists')}
        >
          playlists
        </button>
        <button
          className={`sidebar-nav-btn ${view === 'jobs' ? 'active' : ''}`}
          onClick={() => onViewChange('jobs')}
        >
          jobs
        </button>
        <button
          className={`sidebar-nav-btn ${view === 'download' ? 'active' : ''}`}
          onClick={() => onViewChange('download')}
        >
          download
        </button>
        {selectionCount > 0 && (
          <button
            className="sidebar-nav-btn btn small secondary"
            disabled
          >
            {selectionCount} selected
          </button>
        )}
      </nav>

      <div className="sidebar-playlists">
        <div className="sidebar-section-title">playlists</div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
          <input
            type="text"
            placeholder="new playlist"
            value={newPlaylistName}
            onChange={(e) => setNewPlaylistName(e.target.value)}
            onKeyPress={(e) => {
              if (e.key === 'Enter' && newPlaylistName.trim()) {
                api.createPlaylist(newPlaylistName.trim()).then(() => {
                  setNewPlaylistName('')
                })
              }
            }}
          />
          <button
            className="btn small"
            disabled={!newPlaylistName.trim()}
            onClick={() => {
              if (!newPlaylistName.trim()) return
              api.createPlaylist(newPlaylistName.trim()).then(() => {
                setNewPlaylistName('')
              })
            }}
          >
            create
          </button>
        </div>
        <div className="playlists-grid">
          {playlists.map((pl) => (
            <PlaylistCard
              key={pl.name}
              playlist={pl}
              onClick={onSelectPlaylist}
              selected={selectedPlaylist === pl.name}
            />
          ))}
          {playlists.length === 0 && (
            <div className="muted" style={{ gridColumn: '1 / -1', textAlign: 'center', padding: 12 }}>
              no playlists yet. create one above.
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
