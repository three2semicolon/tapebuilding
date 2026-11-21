/**
 * PlaylistDetailView - single playlist detail: track table, ops, detach/reattach,
 * refresh/rebuild, undo, drag-to-reorder, clipboard, ghost actions.
 * Uses TanStack Query with etag-based optimistic updates.
 */

import { useCallback, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSelectedPaths, useSelectionStore } from '@/store/useSelectionStore'
import {
  api,
  type PlaylistDetail,
  type Op,
} from '@/services/api'
import { TrackTable } from './TrackTable'
import { CoverImage } from './CoverImage'
import { TrackMenu } from './TrackMenu'
import { AudioPlayer } from './AudioPlayer'

interface PlaylistDetailViewProps {
  name: string
  onBack: () => void
  onGoToArtist?: (artist: string) => void
  onGoToAlbum?: (artist: string, album: string) => void
}

export function PlaylistDetailView({
  name,
  onBack,
  onGoToArtist,
  onGoToAlbum,
}: PlaylistDetailViewProps) {
  const queryClient = useQueryClient()
  const selectedPaths = useSelectedPaths()
  const setSelection = useSelectionStore((s) => s.setSelection)
  const setPlaylistContext = useSelectionStore((s) => s.setPlaylistContext)
  const clipboard = useSelectionStore((s) => s.clipboard)
  const setClipboard = useSelectionStore((s) => s.setClipboard)

  const etagRef = useRef<string | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState(name)

  // Right-click context menu state
  const [contextMenu, setContextMenu] = useState<{
    x: number
    y: number
  } | null>(null)

  const { data: detail, isLoading, error, refetch } = useQuery({
    queryKey: ['playlist', name],
    queryFn: () => api.getPlaylist(name),
  })

  // all playlists (for add-to-playlist context menu)
  const { data: playlistsData } = useQuery({
    queryKey: ['playlists'],
    queryFn: api.listPlaylists,
  })
  const playlistNames: string[] = (playlistsData?.playlists ?? []).map(
    (p) => p.name
  )

  // membership: which playlists each track appears in
  const entryPaths = detail?.entries.map((e) => e.path!).filter(Boolean) ?? []
  const { data: membershipData } = useQuery({
    queryKey: ['track-membership', name],
    queryFn: () =>
      api.tracksPlaylists(entryPaths) as Promise<{ playlists: Record<string, string[]> }>,
    enabled: entryPaths.length > 0,
  })
  const membership: Record<string, string[]> = membershipData?.playlists ?? {}

  const playlist: PlaylistDetail | undefined = detail

  // --- selection handling -------------------------------------------------
  const handleSelectAll = () => {
    const paths = playlist?.entries
      .filter((e) => e.path)
      .map((e) => e.path!) ?? []
    setSelection(paths)
    setPlaylistContext(name)
  }

  const handleClearSelection = () => {
    setSelection([])
    setPlaylistContext(null)
  }

  const selectedEntryPaths = useMemo(() => {
    const set = new Set(selectedPaths)
    return playlist?.entries.filter((e) => e.path && set.has(e.path)) ?? []
  }, [selectedPaths, playlist?.entries])

  // --- mutate helpers -----------------------------------------------------
  const applyOps = useCallback(
    async (ops: Op[]) => {
      if (!playlist) return
      try {
        const res = await api.applyOps(name, ops, etagRef.current ?? undefined)
        etagRef.current = res.etag
        queryClient.invalidateQueries({ queryKey: ['playlist', name] })
        queryClient.invalidateQueries({ queryKey: ['playlists'] })
      } catch (err) {
        alert(`Failed to apply ops: ${err}`)
      }
    },
    [name, playlist, queryClient]
  )

  const handleRemove = useCallback(() => {
    const ids = selectedEntryPaths.map((e) => e.id).filter((id): id is number => id != null)
    if (ids.length === 0) return
    applyOps([{ op: 'remove', ids }])
    handleClearSelection()
  }, [selectedEntryPaths, applyOps, handleClearSelection])

  const handleReorder = useCallback(
    (fromIndex: number, toIndex: number) => {
      if (!playlist) return
      if (playlist.entries[fromIndex].id == null) return
      applyOps([{ op: 'move', ids: [playlist.entries[fromIndex].id!], to: toIndex }])
      handleClearSelection()
    },
    [playlist, applyOps, handleClearSelection]
  )

  const handleMoveToTop = useCallback(() => {
    const ids = selectedEntryPaths.map((e) => e.id).filter((id): id is number => id != null)
    if (ids.length === 0) return
    applyOps([{ op: 'move', ids, to: 0 }])
    handleClearSelection()
  }, [selectedEntryPaths, applyOps, handleClearSelection])

  const handleMoveToBottom = useCallback(() => {
    const ids = selectedEntryPaths.map((e) => e.id).filter((id): id is number => id != null)
    if (ids.length === 0) return
    const len = playlist?.entries.length ?? 0
    // `to` is the final index of the first moved item: len - n puts the block at the bottom.
    applyOps([{ op: 'move', ids, to: Math.max(0, len - ids.length) }])
    handleClearSelection()
  }, [selectedEntryPaths, playlist?.entries.length, applyOps, handleClearSelection])

  const handleUndo = useCallback(async () => {
    try {
      await api.undoPlaylist(name)
      etagRef.current = null
      queryClient.invalidateQueries({ queryKey: ['playlist', name] })
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
    } catch (err) {
      alert(`Undo failed: ${err}`)
    }
  }, [name, queryClient])

  const handleDetach = useCallback(async () => {
    try {
      await api.detachPlaylist(name)
      etagRef.current = null
      queryClient.invalidateQueries({ queryKey: ['playlist', name] })
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
    } catch (err) {
      alert(`Detach failed: ${err}`)
    }
  }, [name, queryClient])

  const handleReattach = useCallback(async (mode: 'merge' | 'replace') => {
    try {
      await api.reattachPlaylist(name, mode)
      etagRef.current = null
      queryClient.invalidateQueries({ queryKey: ['playlist', name] })
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
    } catch (err) {
      alert(`Reattach failed: ${err}`)
    }
  }, [name, queryClient])

  const handleRefresh = useCallback(async () => {
    try {
      await api.refreshPlaylist(name)
      etagRef.current = null
      queryClient.invalidateQueries({ queryKey: ['playlist', name] })
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
    } catch (err) {
      alert(`Refresh failed: ${err}`)
    }
  }, [name, queryClient])

  const handleRebuild = useCallback(async () => {
    try {
      await api.rebuildPlaylist(name)
      etagRef.current = null
      queryClient.invalidateQueries({ queryKey: ['playlist', name] })
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
    } catch (err) {
      alert(`Rebuild failed: ${err}`)
    }
  }, [name, queryClient])

  const handleRelink = useCallback(async () => {
    try {
      await api.relinkPlaylist(name)
      etagRef.current = null
      queryClient.invalidateQueries({ queryKey: ['playlist', name] })
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      refetch()
    } catch (err) {
      alert(`Relink failed: ${err}`)
    }
  }, [name, queryClient, refetch])

  const handleUploadCover = useCallback(async (file: File) => {
    try {
      await api.uploadCover(name, file)
      queryClient.invalidateQueries({ queryKey: ['playlist', name] })
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      refetch()
    } catch (err) {
      alert(`Failed to upload cover: ${err}`)
    }
  }, [name, queryClient, refetch])

  const handleDeletePlaylist = useCallback(async () => {
    if (!window.confirm(`Delete playlist "${name}"?`)) return
    try {
      await api.deletePlaylist(name)
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      onBack()
    } catch (err) {
      alert(`Delete failed: ${err}`)
    }
  }, [name, queryClient, onBack])

  const handleRenameSave = useCallback(async () => {
    if (!editName.trim() || editName === name) {
      setIsEditing(false)
      return
    }
    try {
      await api.renamePlaylist(name, editName.trim())
      queryClient.invalidateQueries({ queryKey: ['playlist', name] })
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
    } catch (err) {
      alert(`Rename failed: ${err}`)
    }
    setIsEditing(false)
  }, [name, editName, queryClient])

  const handleAddToPlaylist = useCallback(
    async (_paths: string[], playlistName: string) => {
      const paths = selectedEntryPaths.map((e) => e.path!).filter(Boolean)
      if (paths.length === 0) return
      if (playlistName === '__new__') {
        const newName = window.prompt('New playlist name:')
        if (!newName) return
        try {
          await api.createPlaylist(newName)
          queryClient.invalidateQueries({ queryKey: ['playlists'] })
        } catch (err) {
          alert(`Failed to create playlist: ${err}`)
        }
        return
      }
      const entries = playlist?.entries.filter((e) => paths.includes(e.path!)) ?? []
      const ids = entries.map((e) => e.id).filter((id): id is number => id != null)
      try {
        await api.applyOps(playlistName, [{ op: 'add', ids }])
        queryClient.invalidateQueries({ queryKey: ['playlists'] })
      } catch (err) {
        alert(`Failed to add to playlist: ${err}`)
      }
    },
    [selectedEntryPaths, playlist?.entries, queryClient]
  )

  const handleCopy = useCallback(() => {
    const tracks = selectedEntryPaths.map((e) => ({
      path: e.path!,
      artist: e.artist,
      title: e.title,
      album: e.album,
      length: e.length,
    }))
    setClipboard(tracks)
  }, [selectedEntryPaths, setClipboard])

  const handleCut = useCallback(() => {
    const tracks = selectedEntryPaths.map((e) => ({
      path: e.path!,
      artist: e.artist,
      title: e.title,
      album: e.album,
      length: e.length,
    }))
    setClipboard(tracks)
  }, [selectedEntryPaths, setClipboard])

  const handlePasteAfter = useCallback(
    (_paths: string[], _anchorPath: string) => {
      if (clipboard.length === 0) return
      const paths = clipboard.map((t) => t.path).filter(Boolean)
      try {
        void api.applyOps(name, [{ op: 'add', paths }])
        queryClient.invalidateQueries({ queryKey: ['playlist', name] })
        queryClient.invalidateQueries({ queryKey: ['playlists'] })
      } catch (err) {
        alert(`Failed to paste: ${err}`)
      }
    },
    [clipboard, name, queryClient]
  )

  const handlePasteEnd = useCallback(() => {
    if (clipboard.length === 0) return
    const paths = clipboard.map((t) => t.path).filter(Boolean)
    try {
      void api.applyOps(name, [{ op: 'add', paths }])
      queryClient.invalidateQueries({ queryKey: ['playlist', name] })
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
    } catch (err) {
      alert(`Failed to paste: ${err}`)
    }
  }, [clipboard, name, queryClient])

  const handleCopyBotUrl = useCallback(() => {
    const urls = selectedEntryPaths
      .map((e) => e.path)
      .filter(Boolean)
    if (urls.length === 0) return
    navigator.clipboard.writeText(urls.join('\n'))
  }, [selectedEntryPaths])

  const handleCopyPath = useCallback(() => {
    const paths = selectedEntryPaths.map((e) => e.path!).filter(Boolean)
    navigator.clipboard.writeText(paths.join('\n'))
  }, [selectedEntryPaths])

  const handleDownload = useCallback(() => {
    const tracks = selectedEntryPaths
    if (tracks.length === 0) return
    const url = window.prompt(
      'Download URL (spotify/youtube link or search query):',
      ''
    )
    if (!url) return
    void api.createJob('download', url).then(() => {
      // job created; user can watch it on the jobs page
    }).catch((err) => alert(`Failed to start download: ${err}`))
  }, [selectedEntryPaths])

  const handleLinkToFile = useCallback(() => {
    const tracks = selectedEntryPaths
    if (tracks.length === 0) return
    const url = window.prompt('Link URL (spotify/youtube):', '')
    if (!url) return
    const track = playlist?.entries.find((e) => e.path && selectedPaths.has(e.path))
    if (!track) return
    void api.addLink(url, track.path!, track.artist, track.title).then(() => {
      refetch()
    }).catch((err) => alert(`Failed to link: ${err}`))
  }, [selectedEntryPaths, playlist?.entries, selectedPaths, refetch])

  const handleGoToArtist = useCallback((artist: string) => {
    onGoToArtist?.(artist)
  }, [onGoToArtist])

  const handleGoToAlbum = useCallback((_artist: string, album: string) => {
    onGoToAlbum?.(_artist, album)
  }, [onGoToAlbum])

  const handleEditTags = useCallback(() => {
    const paths = selectedEntryPaths.map((e) => e.path!).filter(Boolean)
    if (paths.length === 0) return
    window.location.hash = `edit:${paths.join(',')}`
  }, [selectedEntryPaths])

  // right-click context menu
  const handleContextMenu = (_track: any, x: number, y: number) => {
    setContextMenu({ x, y })
  }

  const handleCloseMenu = () => {
    setContextMenu(null)
  }

  if (isLoading) {
    return <div className="loading">loading playlist…</div>
  }

  if (error) {
    return (
      <div className="error-state">
        <div className="title">failed to load playlist</div>
        <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>{String(error)}</div>
        <button className="btn" onClick={() => refetch()} style={{ marginTop: 10 }}>
          retry
        </button>
      </div>
    )
  }

  if (!playlist) {
    return <div className="loading">playlist not found</div>
  }

  const entries = playlist.entries
  const ghosts = playlist.ghosts
  const kindLabel = playlist.kind === 'synced' ? 'synced'
    : playlist.kind === 'detached' ? 'detached'
    : 'local'

  const mins = Math.floor(playlist.duration / 60)
  const secs = Math.floor(playlist.duration % 60).toString().padStart(2, '0')

  return (
    <div className="app">
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button className="btn small secondary" onClick={onBack}>
            ← back
          </button>
          <h2 style={{ margin: 0 }}>
            {isEditing ? (
              <input
                id="rename-playlist"
                autoFocus
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onBlur={() => setIsEditing(false)}
                onKeyPress={(e) => e.key === 'Enter' && setIsEditing(false)}
                style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 20,
                  background: 'transparent',
                  color: 'var(--outline)',
                  border: 'none',
                  padding: 0,
                  width: 'auto',
                }}
              />
            ) : (
              editName
            )}
          </h2>
          {isEditing ? (
            <>
              <button className="btn small" onClick={() => setIsEditing(false)}>cancel</button>
              <button className="btn small" onClick={handleRenameSave}>save</button>
            </>
          ) : (
            <button
              className="btn small"
              onClick={() => {
                setEditName(name)
                setIsEditing(true)
              }}
            >
              rename
            </button>
          )}
          <span className={`tag ${kindLabel}`}>{kindLabel}</span>
          {playlist.edited && <span className="tag warn">edited</span>}
          <span className="tag">{playlist.etag}</span>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={handleUndo} disabled={!playlist.edited}>
            undo
          </button>
          {playlist.kind !== 'detached' && (
            <button className="btn small secondary" onClick={handleRelink}>
              relink ghosts
            </button>
          )}
          <button className="btn danger" onClick={handleDeletePlaylist}>
            delete
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: 16 }}>
        {/* sidebar within detail view */}
        <div className="card" style={{ height: 'fit-content' }}>
          <CoverImage playlist={playlist} size={140} />
          <div style={{ padding: 10 }}>
            <input
              type="file"
              accept="image/*"
              id="cover-upload"
              style={{ display: 'none' }}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handleUploadCover(file)
              }}
            />
            <label
              htmlFor="cover-upload"
              style={{
                display: 'inline-block',
                marginTop: 8,
                fontSize: 11,
                color: 'var(--outline-soft)',
                cursor: 'pointer',
                textDecoration: 'underline',
              }}
            >
              replace cover image
            </label>
            <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>
              {entries.length} track{entries.length !== 1 ? 's' : ''}
            </div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
              {mins}:{secs}
            </div>
            {playlist.source_id && (
              <div className="muted" style={{ fontSize: 11, marginBottom: 10, wordBreak: 'break-all' }}>
                source: {playlist.source_id}
              </div>
            )}
            {playlist.kind === 'synced' && (
              <button className="btn small secondary" style={{ width: '100%', marginBottom: 6 }} onClick={handleDetach}>
                detach
              </button>
            )}
            {playlist.kind === 'detached' && (
              <>
                <button className="btn small" style={{ width: '48%', marginRight: 4 }} onClick={() => handleReattach('merge')}>
                  reattach
                </button>
                <button className="btn small" style={{ width: '48%' }} onClick={() => handleReattach('replace')}>
                  replace
                </button>
              </>
            )}
            {playlist.kind !== 'detached' && (
              <>
                <button className="btn small" style={{ width: '48%', marginRight: 4 }} onClick={handleRefresh}>
                  refresh
                </button>
                <button className="btn small" style={{ width: '48%' }} onClick={handleRebuild}>
                  rebuild
                </button>
              </>
            )}
            <button className="btn small" style={{ width: '100%' }} onClick={handleClearSelection}>
              clear selection
            </button>
          </div>
        </div>

        {/* main: track table */}
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>{entries.length} tracks</h3>
            <div style={{ display: 'flex', gap: 8 }}>
              {selectedPaths.size > 0 && (
                <>
                  <button className="btn small secondary" onClick={handleSelectAll} disabled={selectedPaths.size === entries.length}>
                    select all
                  </button>
                  <button className="btn small danger" onClick={handleRemove}>
                    remove
                  </button>
                  <button className="btn small" onClick={handleCopyBotUrl}>
                    bot url
                  </button>
                  <button className="btn small" onClick={handleCopy}>
                    copy
                  </button>
                  <button className="btn small" onClick={handlePasteEnd} disabled={clipboard.length === 0}>
                    paste
                  </button>
                </>
              )}
              <button className="btn small secondary" onClick={handleClearSelection}>
                clear
              </button>
            </div>
          </div>

          {selectedPaths.size > 0 && (
            <div className="muted" style={{ marginBottom: 10 }}>
              {selectedPaths.size} selected{clipboard.length > 0 ? ` · ${clipboard.length} in clipboard` : ''}
            </div>
          )}

          {/* inline audio player: plays the first selected track */}
          {selectedEntryPaths.length > 0 && (
            <AudioPlayer
              srcPath={selectedEntryPaths[0].path ?? null}
              title={selectedEntryPaths[0].title}
              artist={selectedEntryPaths[0].artist}
            />
          )}

          <TrackTable
            tracks={entries}
            selected={Array.from(selectedPaths)}
            onRowClick={() => {}}
            onSelectionChange={(paths) => {
              setSelection(paths)
              setPlaylistContext(paths.length > 0 ? name : null)
            }}
            onReorder={handleReorder}
            onContextMenu={handleContextMenu}
            showPlaylistColumn={false}
            membership={membership}
          />

          {ghosts.length > 0 && (
            <div className="card" style={{ marginTop: 12, borderColor: 'var(--text-dark)' }}>
              <h3 style={{ marginTop: 0, marginRight: 0, marginBottom: 8, marginLeft: 0, fontSize: 14, color: '#b89bb8' }}>
                {ghosts.length} ghost{ghosts.length !== 1 ? 's' : ''} (not in crate)
              </h3>
              <TrackTable
                tracks={ghosts}
                selected={Array.from(selectedPaths)}
                onRowClick={() => {}}
                onContextMenu={handleContextMenu}
                showPlaylistColumn={false}
                membership={membership}
              />
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                <button className="btn small secondary" onClick={handleRelink}>
                  relink all ghosts
                </button>
                <button className="btn small" onClick={() => {
                  const paths = ghosts.map((g) => g.path!).filter(Boolean)
                  selectedEntryPaths.length === 0 && setSelection(paths)
                }}>
                  select all ghosts
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* track menu */}
      <TrackMenu
        open={contextMenu != null}
        onOpenChange={handleCloseMenu}
        x={contextMenu?.x ?? 0}
        y={contextMenu?.y ?? 0}
        selectedPaths={Array.from(selectedPaths)}
        playlist={name}
        playlists={playlistNames}
        trackMembership={membership}
        isSynced={playlist.kind === 'synced'}
        isDetached={playlist.kind === 'detached'}
        onAddToPlaylist={handleAddToPlaylist}
        onRemoveFromPlaylist={handleRemove}
        onCopy={handleCopy}
        onCut={handleCut}
        onPasteAfter={handlePasteAfter}
        onPasteEnd={handlePasteEnd}
        onMoveToTop={handleMoveToTop}
        onMoveToBottom={handleMoveToBottom}
        onCopyBotUrl={handleCopyBotUrl}
        onCopyPath={handleCopyPath}
        onGoToArtist={handleGoToArtist}
        onGoToAlbum={handleGoToAlbum}
        onEditTags={handleEditTags}
        onRelink={() => handleRelink()}
        onDownload={handleDownload}
        onLinkToFile={handleLinkToFile}
        onDetach={handleDetach}
        onReattach={handleReattach}
      />
    </div>
  )
}
