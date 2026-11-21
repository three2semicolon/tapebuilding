/**
 * LibraryView - library browsing with search, filters, selection, clipboard,
 * and virtualized track table.
 */

import { useState, useCallback, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type LibraryParams, type LibraryRow } from '@/services/api'
import { TrackTable } from './TrackTable'
import { TrackMenu } from './TrackMenu'
import {
  useSelectedPaths,
  useSelectionStore,
} from '@/store/useSelectionStore'

interface LibraryViewProps {
  initialFilter?: { artist?: string; album?: string }
  onFilterApplied?: () => void
}

export function LibraryView({
  initialFilter,
  onFilterApplied,
}: LibraryViewProps) {
  const [params, setParams] = useState<LibraryParams>({
    sort: 'artist',
    dir: 'asc',
    offset: 0,
    limit: 100,
  })
  const [query, setQuery] = useState('')
  const [artistFilter, setArtistFilter] = useState(
    initialFilter?.artist ?? ''
  )
  const [albumFilter, setAlbumFilter] = useState(initialFilter?.album ?? '')
  const [playlistFilter, setPlaylistFilter] = useState('')

  // Apply initial filter on mount (e.g. navigating from an artist/album link)
  useEffect(() => {
    if (initialFilter && (initialFilter.artist || initialFilter.album)) {
      setArtistFilter(initialFilter.artist ?? '')
      setAlbumFilter(initialFilter.album ?? '')
      onFilterApplied?.()
    }
  }, [initialFilter, onFilterApplied])

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: [
      'library',
      params,
      query,
      artistFilter,
      albumFilter,
      playlistFilter,
    ],
    queryFn: () =>
      api.getLibrary({
        q: query || undefined,
        artist: artistFilter || undefined,
        album: albumFilter || undefined,
        playlist: playlistFilter || undefined,
        minPlaylists: 1,
        sort: params.sort,
        dir: params.dir,
        offset: params.offset,
        limit: params.limit,
      }),
  })

  const tracks: LibraryRow[] = data?.rows ?? []
  const total = data?.total ?? 0

  // --- selection -----------------------------------------------------------
  const selectedPaths = useSelectedPaths()
  const setSelection = useSelectionStore((s) => s.setSelection)
  const clearSelection = useSelectionStore((s) => s.clearSelection)
  const setPlaylistContext = useSelectionStore((s) => s.setPlaylistContext)
  const clipboard = useSelectionStore((s) => s.clipboard)
  const setClipboard = useSelectionStore((s) => s.setClipboard)

  // --- membership (which playlists each track appears in) ------------------
  const entryPaths = useMemo(
    () => tracks.map((t) => t.path).filter(Boolean),
    [tracks]
  )
  const { data: membershipData } = useQuery({
    queryKey: ['track-membership', 'library', JSON.stringify(entryPaths.sort())],
    queryFn: () =>
      api.tracksPlaylists(entryPaths) as Promise<{
        playlists: Record<string, string[]>
      }>,
    enabled: entryPaths.length > 0,
  })
  const membership: Record<string, string[]> = membershipData?.playlists ?? {}

  const handleSearch = useCallback(() => {
    setParams((p) => ({ ...p, offset: 0 }))
  }, [])

  const handleSelectAll = () => {
    const paths = tracks.filter((t) => t.path).map((t) => t.path)
    setSelection(paths)
    setPlaylistContext(null)
  }

  const handleCopy = () => {
    const trackList = tracks.filter((t) => selectedPaths.has(t.path))
    setClipboard(
      trackList.map((t) => ({
        path: t.path,
        artist: t.artist,
        title: t.title,
        album: t.album,
        length: t.length,
      }))
    )
  }

  const handleCut = () => {
    handleCopy()
    // cut is copy + mark for removal; removal handled by TrackMenu onCut
  }

  const handlePasteAfter = () => {
    alert(
      'Paste is only available inside a playlist view. Open a playlist and paste there.'
    )
  }

  const handlePasteEnd = () => {
    alert(
      'Paste is only available inside a playlist view. Open a playlist and paste there.'
    )
  }

  const handleDownload = () => {
    const track = tracks.find((t) => selectedPaths.has(t.path))
    if (!track) return
    const url = window.prompt(
      'Download URL (spotify/youtube link or search query):',
      ''
    )
    if (!url) return
    void api
      .createJob('download', url)
      .then(() => {
        // job created; user can watch it on the jobs page
      })
      .catch((err) => alert(`Failed to start download: ${err}`))
  }

  if (isLoading) {
    return <div className="loading">loading library…</div>
  }

  if (error) {
    return (
      <div className="error-state">
        <div className="title">failed to load library</div>
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
        <h2>library</h2>
        <div className="page-actions">
          {selectedPaths.size > 0 && (
            <>
              <button
                className="btn small secondary"
                onClick={handleSelectAll}
                disabled={selectedPaths.size === tracks.length}
              >
                select all
              </button>
              <button className="btn small" onClick={handleCopy}>
                copy
              </button>
              <button className="btn small" onClick={handleCut}>
                cut
              </button>
              <button
                className="btn small"
                onClick={handlePasteEnd}
                disabled={clipboard.length === 0}
              >
                paste
              </button>
              <button className="btn small secondary" onClick={clearSelection}>
                clear
              </button>
            </>
          )}
          <button className="btn secondary" onClick={() => api.rescanLibrary()}>
            rescan
          </button>
        </div>
      </div>

      <div className="card">
        <h3>search</h3>
        <div className="form-grid">
          <div className="form-row">
            <label>query</label>
            <input
              id="q"
              placeholder="artist / album / title"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <div className="form-row">
            <label>artist</label>
            <input
              id="f-artist"
              placeholder="artist contains"
              value={artistFilter}
              onChange={(e) => setArtistFilter(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <div className="form-row">
            <label>album</label>
            <input
              id="f-album"
              placeholder="album contains"
              value={albumFilter}
              onChange={(e) => setAlbumFilter(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <div className="form-row">
            <label>playlist</label>
            <select
              id="f-playlist"
              value={playlistFilter}
              onChange={(e) => setPlaylistFilter(e.target.value)}
            >
              <option value="">all</option>
              <option value="none">not in any playlist</option>
            </select>
          </div>
          <div className="form-row" style={{ alignItems: 'flex-end', display: 'flex', gap: 8 }}>
            <button className="btn" onClick={handleSearch}>
              search
            </button>
            <button
              className="btn secondary"
              onClick={() => {
                setQuery('')
                setArtistFilter('')
                setAlbumFilter('')
                setPlaylistFilter('')
                setParams((p) => ({ ...p, offset: 0 }))
              }}
            >
              clear
            </button>
          </div>
        </div>
        <p className="muted" style={{ marginTop: 8 }}>
          {total} track{total !== 1 ? 's' : ''} (showing {tracks.length})
        </p>
      </div>

      <div className="table-wrap">
        <TrackTable
          tracks={tracks}
          selected={Array.from(selectedPaths)}
          onSelectionChange={(paths) => {
            setSelection(paths)
            setPlaylistContext(paths.length > 0 ? null : null)
          }}
          showPlaylistColumn={true}
          membership={membership}
        />
        {tracks.length === 0 && (
          <div className="muted" style={{ textAlign: 'center', padding: 20, marginTop: 10 }}>
            no tracks found. check the archive path, or add music via the downloader.
          </div>
        )}
      </div>

      {total > tracks.length && (
        <div className="muted" style={{ textAlign: 'center', padding: 8 }}>
          showing {tracks.length} of {total} tracks
        </div>
      )}

      {/* track menu - actions on the current selection */}
      <TrackMenu
        selectedPaths={Array.from(selectedPaths)}
        playlist={null}
        onAddToPlaylist={(_paths: string[], playlistName: string) => {
          if (playlistName === '__new__') {
            const newName = window.prompt('New playlist name:')
            if (!newName) return
            api
              .createPlaylist(newName)
              .then(() => {
                // playlist created; user can open it from the sidebar
              })
              .catch((err) => alert(`Failed to create playlist: ${err}`))
            return
          }
          alert(
            'Use the playlist view to add tracks to an existing playlist.'
          )
        }}
        onRemoveFromPlaylist={() => {}}
        onCopy={handleCopy}
        onCut={handleCut}
        onPasteAfter={handlePasteAfter}
        onPasteEnd={handlePasteEnd}
        onMoveToTop={() => {}}
        onMoveToBottom={() => {}}
        onCopyBotUrl={() => {
          const urls = tracks
            .filter((t) => selectedPaths.has(t.path) && t.url)
            .map((t) => t.url)
            .filter(Boolean)
          if (urls.length > 0) {
            navigator.clipboard.writeText(urls.join('\n'))
          }
        }}
        onCopyPath={() => {
          const paths = tracks
            .filter((t) => selectedPaths.has(t.path) && t.path)
            .map((t) => t.path)
            .filter(Boolean)
          navigator.clipboard.writeText(paths.join('\n'))
        }}
        onGoToArtist={(_artist) => {}}
        onGoToAlbum={(_artist, _album) => {}}
        onEditTags={() => {
          alert('Edit tags not yet available in library view.')
        }}
        onRelink={() => {}}
        onDownload={handleDownload}
        onLinkToFile={() => {
          alert('Link to file not yet available in library view.')
        }}
        onDetach={() => {}}
        onReattach={() => {}}
        children={
          <button className="sr-only">open track menu</button>
        }
      />
    </div>
  )
}
