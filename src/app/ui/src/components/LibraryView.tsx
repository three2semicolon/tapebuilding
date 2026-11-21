/**
 * LibraryView - library browsing with search, filters, selection, clipboard,
 * and virtualized track table.
 */

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
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
  const [advanced, setAdvanced] = useState(false)

  // Right-click context menu state
  const [contextMenu, setContextMenu] = useState<{
    x: number
    y: number
  } | null>(null)

  // Apply initial filter on mount (e.g. navigating from an artist/album link)
  useEffect(() => {
    if (initialFilter && (initialFilter.artist || initialFilter.album)) {
      setArtistFilter(initialFilter.artist ?? '')
      setAlbumFilter(initialFilter.album ?? '')
      onFilterApplied?.()
    }
  }, [initialFilter, onFilterApplied])

  const queryInputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearDebounce = useCallback(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
      debounceRef.current = null
    }
  }, [])

  const handleSearch = useCallback(() => {
    setParams((p) => ({ ...p, offset: 0 }))
  }, [])

  const debouncedSearch = useCallback(() => {
    clearDebounce()
    debounceRef.current = setTimeout(handleSearch, 300)
  }, [clearDebounce, handleSearch])

  // Focus query input on mount and when advanced search opens
  useEffect(() => {
    queryInputRef.current?.focus()
  }, [advanced])

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => clearDebounce()
  }, [clearDebounce])

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

  // --- playlists (for add-to-playlist context menu) -------------------------
  const { data: playlistsData } = useQuery({
    queryKey: ['playlists'],
    queryFn: api.listPlaylists,
  })
  const playlistNames: string[] = (playlistsData?.playlists ?? []).map(
    (p) => p.name
  )

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

  // --- right-click context menu --------------------------------------------
  const handleContextMenu = (_track: LibraryRow, x: number, y: number) => {
    setContextMenu({ x, y })
  }

  const handleCloseMenu = () => {
    setContextMenu(null)
  }

  const handleAddToPlaylist = (_paths: string[], playlistName: string) => {
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
          {/* Default: single query box */}
          <div className="form-row">
            <label>query</label>
            <input
              id="q"
              ref={queryInputRef}
              placeholder="artist / album / title / year"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                debouncedSearch()
              }}
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  clearDebounce()
                  handleSearch()
                }
              }}
            />
          </div>

          {advanced && (
            <>
              <div className="form-row">
                <label>artist</label>
                <input
                  id="f-artist"
                  placeholder="artist contains"
                  value={artistFilter}
                  onChange={(e) => {
                    setArtistFilter(e.target.value)
                    debouncedSearch()
                  }}
                  onKeyPress={(e) => {
                    if (e.key === 'Enter') {
                      clearDebounce()
                      handleSearch()
                    }
                  }}
                />
              </div>
              <div className="form-row">
                <label>album</label>
                <input
                  id="f-album"
                  placeholder="album contains"
                  value={albumFilter}
                  onChange={(e) => {
                    setAlbumFilter(e.target.value)
                    debouncedSearch()
                  }}
                  onKeyPress={(e) => {
                    if (e.key === 'Enter') {
                      clearDebounce()
                      handleSearch()
                    }
                  }}
                />
              </div>
              <div className="form-row">
                <label>playlist</label>
                <select
                  id="f-playlist"
                  value={playlistFilter}
                  onChange={(e) => {
                    setPlaylistFilter(e.target.value)
                    debouncedSearch()
                  }}
                >
                  <option value="">all</option>
                  <option value="none">not in any playlist</option>
                </select>
              </div>
            </>
          )}

          <div className="form-row" style={{ alignItems: 'flex-end', display: 'flex', gap: 8, flexDirection: 'column' }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn" onClick={handleSearch}>
                search
              </button>
              <button
                className="btn secondary"
                onClick={() => {
                  clearDebounce()
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
            <button
              className="btn secondary"
              style={{ fontSize: 11, padding: '4px 8px' }}
              onClick={() => setAdvanced(!advanced)}
            >
              {advanced ? 'simple search' : 'advanced search'}
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
          onContextMenu={handleContextMenu}
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
        open={contextMenu != null}
        onOpenChange={handleCloseMenu}
        x={contextMenu?.x ?? 0}
        y={contextMenu?.y ?? 0}
        selectedPaths={Array.from(selectedPaths)}
        playlist={null}
        playlists={playlistNames}
        trackMembership={membership}
        onAddToPlaylist={handleAddToPlaylist}
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
      />
    </div>
  )
}
