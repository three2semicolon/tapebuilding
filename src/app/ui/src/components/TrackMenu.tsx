/**
 * TrackMenu - Spotify-style track context menu (Radix UI ContextMenu).
 * Acts on the current selection, not just the clicked row.
 *
 * Supports controlled open mode: pass `open`, `onOpenChange`, `x`, `y` to
 * open the menu at a specific screen position (e.g. from a right-click).
 * Pass `playlists` + `trackMembership` to render the add-to-playlist
 * submenu as a checklist (✓ = already in playlist).
 */

import { useEffect, useRef } from 'react'
import * as ContextMenuPrimitive from '@radix-ui/react-context-menu'
import { ChevronRight, Copy, ExternalLink, Folder, Music, Trash2 } from 'lucide-react'

const ContextMenu = ContextMenuPrimitive.Root
const ContextMenuTrigger = ContextMenuPrimitive.Trigger
const ContextMenuContent = ContextMenuPrimitive.Content
const ContextMenuItem = ContextMenuPrimitive.Item
const ContextMenuLabel = ContextMenuPrimitive.Label
const ContextMenuSeparator = ContextMenuPrimitive.Separator
const ContextMenuSub = ContextMenuPrimitive.Sub
const ContextMenuSubContent = ContextMenuPrimitive.SubContent
const ContextMenuSubTrigger = ContextMenuPrimitive.SubTrigger

interface TrackMenuProps {
  /** Paths of the selected tracks (derived from the store). */
  selectedPaths: string[]
  /** Playlist the menu is scoped to (null when in library view). */
  playlist: string | null
  /** Whether the clicked track is a ghost (missing file). */
  isGhost?: boolean
  /** Whether the playlist is synced (so detach/reattach options show). */
  isSynced?: boolean
  /** Whether the playlist is detached. */
  isDetached?: boolean
  /** Controlled open state (for right-click triggering). */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Screen X position for the menu (used with controlled open). */
  x?: number
  /** Screen Y position for the menu (used with controlled open). */
  y?: number
  /** All playlist names, for the add-to-playlist checklist submenu. */
  playlists: string[]
  /** path -> playlist names, used to determine ✓ state. */
  trackMembership: Record<string, string[]>
  onAddToPlaylist: (paths: string[], playlistName: string) => void
  onRemoveFromPlaylist: (paths: string[]) => void
  onCopy: (paths: string[]) => void
  onCut: (paths: string[]) => void
  onPasteAfter: (paths: string[], anchorPath: string) => void
  onPasteEnd: (paths: string[]) => void
  onMoveToTop: (paths: string[]) => void
  onMoveToBottom: (paths: string[]) => void
  onCopyBotUrl: (paths: string[]) => void
  onCopyPath: (paths: string[]) => void
  onGoToArtist: (artist: string) => void
  onGoToAlbum: (artist: string, album: string) => void
  onEditTags: (paths: string[]) => void
  onRelink: (paths: string[]) => void
  onDownload: (paths: string[]) => void
  onLinkToFile: (paths: string[]) => void
  onDetach: () => void
  onReattach: (mode: 'merge' | 'replace') => void
}

export function TrackMenu({
  selectedPaths,
  playlist,
  isGhost = false,
  isSynced = false,
  isDetached = false,
  open = false,
  onOpenChange,
  x = 0,
  y = 0,
  playlists = [],
  trackMembership = {},
  onAddToPlaylist,
  onRemoveFromPlaylist,
  onCopy,
  onCut,
  onPasteAfter,
  onPasteEnd,
  onMoveToTop,
  onMoveToBottom,
  onCopyBotUrl,
  onCopyPath,
  onGoToArtist,
  onGoToAlbum,
  onEditTags,
  onRelink,
  onDownload,
  onLinkToFile,
  onDetach,
  onReattach,
}: TrackMenuProps) {
  // A track is considered "in" a playlist if ALL selected tracks are members.
  const triggerRef = useRef<HTMLButtonElement>(null)

  // Auto-open the menu at the right-click position. Radix v1.0.0's Root doesn't
  // accept a controlled `open` prop, so we programmatically click the hidden
  // trigger (positioned at x/y by the parent) whenever the menu should open.
  useEffect(() => {
    if (open && triggerRef.current) {
      triggerRef.current.click()
    }
  }, [open, x, y])

  // A track is considered "in" a playlist if ALL selected tracks are members.
  const isInPlaylist = (playlistName: string) =>
    selectedPaths.length > 0 &&
    selectedPaths.every((p) => (trackMembership[p] ?? []).includes(playlistName))

  // Playlists that contain at least one of the selected tracks (for "In playlists" submenu).
  const memberPlaylists = useMemoMemberPlaylists(selectedPaths, trackMembership)

  return (
    <ContextMenu onOpenChange={onOpenChange}>
      {/* Hidden trigger positioned at (x, y) so the menu opens at the right-click spot. */}
      <ContextMenuTrigger asChild>
        <button
          ref={triggerRef}
          style={{
            position: 'fixed',
            left: x,
            top: y,
            width: 1,
            height: 1,
            overflow: 'hidden',
            border: 'none',
            background: 'none',
            padding: 0,
            margin: 0,
            opacity: 0,
          }}
        >
          trigger
        </button>
      </ContextMenuTrigger>
      <ContextMenuContent
        className="track-menu"
        style={{
          minWidth: 220,
        }}
      >
        {/* -------- add to playlist -------- */}
        <ContextMenuSub>
          <ContextMenuSubTrigger className="track-menu-item">
            <Music className="track-menu-icon" size={14} strokeWidth={2} />
            Add to playlist
            <ChevronRight className="track-menu-subarrow" size={14} strokeWidth={2} />
          </ContextMenuSubTrigger>
          <ContextMenuSubContent className="track-menu-sub">
            <ContextMenuLabel className="track-menu-label">playlists</ContextMenuLabel>
            {playlists.length === 0 ? (
              <ContextMenuItem className="track-menu-item muted">no playlists</ContextMenuItem>
            ) : (
              <>
                <ContextMenuItem
                  className="track-menu-item"
                  onClick={() => onAddToPlaylist(selectedPaths, '__new__')}
                >
                  + New playlist
                </ContextMenuItem>
                <ContextMenuSeparator />
                {playlists.map((p) => (
                  <ContextMenuItem
                    key={p}
                    className="track-menu-item"
                    onClick={() => onAddToPlaylist(selectedPaths, p)}
                  >
                    {isInPlaylist(p) ? '✓ ' : ''}{p}
                  </ContextMenuItem>
                ))}
              </>
            )}
          </ContextMenuSubContent>
        </ContextMenuSub>

        <ContextMenuSeparator />

        {/* -------- remove / in playlists -------- */}
        {playlist && (
          <ContextMenuItem
            className="track-menu-item"
            onClick={() => onRemoveFromPlaylist(selectedPaths)}
          >
            <Trash2 className="track-menu-icon" size={14} strokeWidth={2} />
            Remove from this playlist
          </ContextMenuItem>
        )}

        <ContextMenuSub>
          <ContextMenuSubTrigger className="track-menu-item">
            <Folder className="track-menu-icon" size={14} strokeWidth={2} />
            In playlists
            <ChevronRight className="track-menu-subarrow" size={14} strokeWidth={2} />
          </ContextMenuSubTrigger>
          <ContextMenuSubContent className="track-menu-sub">
            <ContextMenuLabel className="track-menu-label">membership</ContextMenuLabel>
            {memberPlaylists.length === 0 ? (
              <ContextMenuItem className="track-menu-item muted">
                not in any playlist
              </ContextMenuItem>
            ) : (
              memberPlaylists.map((p) => (
                <ContextMenuItem key={p} className="track-menu-item">
                  {p}
                </ContextMenuItem>
              ))
            )}
          </ContextMenuSubContent>
        </ContextMenuSub>

        <ContextMenuSeparator />

        {/* -------- clipboard -------- */}
        <ContextMenuItem
          className="track-menu-item"
          onClick={() => onCopy(selectedPaths)}
        >
          <Copy className="track-menu-icon" size={14} strokeWidth={2} />
          Copy
        </ContextMenuItem>
        <ContextMenuItem
          className="track-menu-item"
          onClick={() => onCut(selectedPaths)}
        >
          <Trash2 className="track-menu-icon" size={14} strokeWidth={2} />
          Cut
        </ContextMenuItem>
        <ContextMenuItem
          className="track-menu-item"
          onClick={() => onPasteAfter(selectedPaths, selectedPaths[0] || '')}
        >
          Paste after
        </ContextMenuItem>
        <ContextMenuItem
          className="track-menu-item"
          onClick={() => onPasteEnd(selectedPaths)}
        >
          Paste to end
        </ContextMenuItem>

        <ContextMenuSeparator />

        {/* -------- move -------- */}
        {playlist && (
          <>
            <ContextMenuItem
              className="track-menu-item"
              onClick={() => onMoveToTop(selectedPaths)}
            >
              <Music className="track-menu-icon" size={14} strokeWidth={2} />
              Move to top
            </ContextMenuItem>
            <ContextMenuItem
              className="track-menu-item"
              onClick={() => onMoveToBottom(selectedPaths)}
            >
              Move to bottom
            </ContextMenuItem>
            <ContextMenuSeparator />
          </>
        )}

        {/* -------- URLs / paths -------- */}
        <ContextMenuItem
          className="track-menu-item"
          onClick={() => onCopyBotUrl(selectedPaths)}
        >
          <ExternalLink className="track-menu-icon" size={14} strokeWidth={2} />
          Copy bot URL
        </ContextMenuItem>
        <ContextMenuItem
          className="track-menu-item"
          onClick={() => onCopyPath(selectedPaths)}
        >
          Copy path
        </ContextMenuItem>

        <ContextMenuSeparator />

        {/* -------- navigation -------- */}
        <ContextMenuItem
          className="track-menu-item"
          onClick={() => onGoToArtist('')}
        >
          Go to artist
        </ContextMenuItem>
        <ContextMenuItem
          className="track-menu-item"
          onClick={() => onGoToAlbum('', '')}
        >
          Go to album
        </ContextMenuItem>

        <ContextMenuSeparator />

        {/* -------- edit / relink -------- */}
        <ContextMenuItem
          className="track-menu-item"
          onClick={() => onEditTags(selectedPaths)}
        >
          Edit tags…
        </ContextMenuItem>
        {isGhost && (
          <>
            <ContextMenuItem
              className="track-menu-item"
              onClick={() => onRelink(selectedPaths)}
            >
              Relink…
            </ContextMenuItem>
            <ContextMenuItem
              className="track-menu-item"
              onClick={() => onDownload(selectedPaths)}
            >
              Download
            </ContextMenuItem>
            <ContextMenuItem
              className="track-menu-item"
              onClick={() => onLinkToFile(selectedPaths)}
            >
              Link to file…
            </ContextMenuItem>
          </>
        )}

        <ContextMenuSeparator />

        {/* -------- playlist-level (synced) -------- */}
        {playlist && isSynced && (
          <>
            <ContextMenuItem
              className="track-menu-item"
              onClick={() => onDetach()}
            >
              Detach from Spotify
            </ContextMenuItem>
            {isDetached && (
              <>
                <ContextMenuItem
                  className="track-menu-item"
                  onClick={() => onReattach('merge')}
                >
                  Reattach (merge)
                </ContextMenuItem>
                <ContextMenuItem
                  className="track-menu-item"
                  onClick={() => onReattach('replace')}
                >
                  Reattach (replace)
                </ContextMenuItem>
              </>
            )}
          </>
        )}
      </ContextMenuContent>
    </ContextMenu>
  )
}

function useMemoMemberPlaylists(
  selectedPaths: string[],
  trackMembership: Record<string, string[]>
): string[] {
  if (selectedPaths.length === 0) return []
  // Intersection: playlists that contain ALL selected tracks.
  const first = (trackMembership[selectedPaths[0]] ?? []).slice()
  const rest = selectedPaths.slice(1)
  const result = first.filter((p) =>
    rest.every((path) => (trackMembership[path] ?? []).includes(p))
  )
  return result
}
