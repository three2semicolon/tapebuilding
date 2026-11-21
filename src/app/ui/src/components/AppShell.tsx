/**
 * AppShell - the main layout: sidebar + main pane. Handles routing between
 * library, playlists index, a single playlist detail view, jobs, and download.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Playlist } from '@/services/api'
import { Sidebar } from './Sidebar'
import { LibraryView } from './LibraryView'
import { PlaylistsView } from './PlaylistsView'
import { PlaylistDetailView } from './PlaylistDetailView'
import { JobsView } from './JobsView'
import { DownloadView } from './DownloadView'

type View = 'library' | 'playlists' | 'detail' | 'jobs' | 'download'

interface AppShellProps {
  className?: string
}

export function AppShell({ className }: AppShellProps) {
  const [view, setView] = useState<View>('library')
  const [selectedPlaylist, setSelectedPlaylist] = useState<string | null>(null)
  const [libraryFilter, setLibraryFilter] = useState<{
    artist?: string
    album?: string
  } | null>(null)

  const { data } = useQuery({
    queryKey: ['playlists'],
    queryFn: api.listPlaylists,
  })

  const playlists: Playlist[] = data?.playlists ?? []

  const handleGoToArtist = (artist: string) => {
    setLibraryFilter({ artist })
    setView('library')
  }

  const handleGoToAlbum = (_artist: string, album: string) => {
    setLibraryFilter({ album })
    setView('library')
  }

  return (
    <div className={`shell ${className ?? ''}`}>
      <Sidebar
        view={view}
        playlists={playlists}
        selectedPlaylist={selectedPlaylist}
        onViewChange={(v) => {
          setView(v)
          if (v !== 'detail') setSelectedPlaylist(null)
        }}
        onSelectPlaylist={(name) => {
          setSelectedPlaylist(name)
          setView('detail')
        }}
      />
      <div className="main-pane">
        {view === 'library' && (
          <LibraryView
            initialFilter={libraryFilter ?? undefined}
            onFilterApplied={() => setLibraryFilter(null)}
          />
        )}
        {view === 'playlists' && (
          <PlaylistsView onSelectPlaylist={(name) => {
            setSelectedPlaylist(name)
            setView('detail')
          }} />
        )}
        {view === 'detail' && selectedPlaylist && (
          <PlaylistDetailView
            name={selectedPlaylist}
            onBack={() => {
              setView('library')
              setSelectedPlaylist(null)
              setLibraryFilter(null)
            }}
            onGoToArtist={handleGoToArtist}
            onGoToAlbum={handleGoToAlbum}
          />
        )}
        {view === 'download' && <DownloadView onBack={() => setView('library')} />}
        {view === 'jobs' && <JobsView onRefresh={() => setView('library')} />}
      </div>
    </div>
  )
}
