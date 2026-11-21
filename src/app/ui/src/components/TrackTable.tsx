/**
 * TrackTable - virtualized track table shared by library and playlist views.
 * Uses @tanstack/react-virtual for performant rendering and @dnd-kit for
 * drag-to-reorder within playlists. Selection is controlled via the `selected`
 * prop; row clicks call `onSelectionChange` with the new path set.
 * No checkboxes — click selects, ctrl/cmd+click toggles, shift+click selects
 * a range, right-click opens the context menu.
 */

import {
  DndContext,
  DragOverlay,
  type DragEndEvent as DragEndEventType,
  PointerSensor,
  useSensors,
} from '@dnd-kit/core'
import { closestCenter } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useCallback, useMemo, useRef, useState } from 'react'
import { type LibraryRow, type PlaylistEntry } from '@/services/api'

type TrackRow = LibraryRow | PlaylistEntry

interface TrackTableProps {
  tracks: TrackRow[]
  /** Externally controlled selection (array of paths). */
  selected?: string[]
  onRowClick?: (track: TrackRow) => void
  onSelectionChange?: (paths: string[]) => void
  onContextMenu?: (track: TrackRow, x: number, y: number) => void
  /** Called when a drag reorder completes: (fromIndex, toIndex). */
  onReorder?: (fromIndex: number, toIndex: number) => void
  rowHeight?: number
  overscan?: number
  showPlaylistColumn?: boolean
  /** path -> playlist names, for the "appears in" column */
  membership?: Record<string, string[]>
}

export function TrackTable({
  tracks,
  selected: selectedProp,
  onRowClick,
  onSelectionChange,
  onContextMenu,
  onReorder,
  rowHeight = 32,
  overscan = 10,
  showPlaylistColumn = false,
  membership,
}: TrackTableProps) {
  const parentRef = useRef<HTMLDivElement>(null)
  const [internalSelected, setInternalSelected] = useState<Set<string>>(new Set())
  const anchorIndexRef = useRef<number | null>(null)

  // Controlled selection: use prop if provided, otherwise internal state.
  const selectedSet = useMemo(
    () => (selectedProp ? new Set(selectedProp) : internalSelected),
    [selectedProp, internalSelected]
  )

  const sensors = useSensors({ sensor: PointerSensor, options: {} })

  const virtualizer = useVirtualizer({
    count: tracks.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan,
  })

  const totalHeight = virtualizer.getTotalSize()
  const virtualItems = virtualizer.getVirtualItems()

  const isSelected = (path: string) => selectedSet.has(path)

  const handleSelectionChange = useCallback(
    (paths: string[]) => {
      setInternalSelected(new Set(paths))
      onSelectionChange?.(paths)
    },
    [onSelectionChange]
  )

  const handleRowClick = useCallback(
    (e: React.MouseEvent, index: number, path: string) => {
      if ((e.target as HTMLElement).closest('a')) return

      if (e.shiftKey && anchorIndexRef.current != null) {
        // Range selection from anchor to current
        const start = Math.min(anchorIndexRef.current, index)
        const end = Math.max(anchorIndexRef.current, index)
        const next = new Set(selectedSet)
        for (let i = start; i <= end; i++) {
          const p = tracks[i].path
          if (p) next.add(p)
        }
        handleSelectionChange([...next])
      } else if (e.ctrlKey || e.metaKey) {
        // Toggle individual track
        const next = new Set(selectedSet)
        if (next.has(path)) next.delete(path)
        else next.add(path)
        handleSelectionChange([...next])
        anchorIndexRef.current = index
      } else {
        // Select only this track
        const next = path ? [path] : []
        handleSelectionChange(next)
        anchorIndexRef.current = index
      }
      onRowClick?.(tracks[index])
    },
    [tracks, selectedSet, handleSelectionChange, onRowClick]
  )

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, index: number) => {
      e.preventDefault()
      onContextMenu?.(tracks[index], e.clientX, e.clientY)
    },
    [tracks, onContextMenu]
  )

  const handleDragEnd = (event: DragEndEventType) => {
    if (!onReorder) return
    const { active, over } = event
    if (!over || over.id === active.id) return
    const activeId = active.id as string
    const overId = over.id as string
    const fromIndex = tracks.findIndex((t) => t.path === activeId)
    const toIndex = tracks.findIndex((t) => t.path === overId)
    if (fromIndex >= 0 && toIndex >= 0 && fromIndex !== toIndex) {
      onReorder(fromIndex, toIndex)
    }
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <div
        ref={parentRef}
        className="table-wrap"
        style={{ height: '100%', overflow: 'auto', position: 'relative' }}
      >
        <div style={{ height: totalHeight, position: 'relative' }}>
          {virtualItems.map((item) => {
            const track = tracks[item.index]
            const path = track.path || ''
            return (
              <SortableTrackRow
                key={path}
                track={track}
                index={item.index}
                virtualItem={item}
                isSelected={isSelected(path)}
                onClick={(e) => handleRowClick(e, item.index, path)}
                onContextMenu={(e) => handleContextMenu(e, item.index)}
                showPlaylistColumn={showPlaylistColumn}
                memberships={membership?.[path] ?? []}
              />
            )
          })}
          {onReorder && <DragOverlay />}
        </div>
      </div>
    </DndContext>
  )
}

interface SortableTrackRowProps {
  track: TrackRow
  index: number
  virtualItem: { start: number; size: number }
  isSelected: boolean
  onClick: (e: React.MouseEvent) => void
  onContextMenu: (e: React.MouseEvent) => void
  showPlaylistColumn: boolean
  memberships: string[]
}

function SortableTrackRow({
  track,
  index,
  virtualItem,
  onClick,
  onContextMenu,
  showPlaylistColumn,
  memberships,
}: SortableTrackRowProps) {
  const { attributes, listeners, setNodeRef, transform } = useSortable({
    id: track.path || `row-${index}`,
  })

  const artist = 'artist' in track ? track.artist : ''
  const title = 'title' in track ? track.title : ''
  const album = 'album' in track ? track.album : ''
  const length = 'length' in track ? track.length : 0
  const url = 'url' in track ? track.url : ''

  const mins = Math.floor(length / 60)
  const secs = Math.floor(length % 60).toString().padStart(2, '0')
  const durationStr = length > 0 ? `${mins}:${secs}` : '–'

  const dragOffset = transform ? ` translate(${transform.x}px, ${transform.y}px)` : ''
  const style: React.CSSProperties = {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: virtualItem.size,
    transform: `translateY(${virtualItem.start}px)${dragOffset}`,
    display: 'flex',
    alignItems: 'center',
    width: '100%',
  }

  const handleRowClick = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('a')) return
    onClick(e)
  }

  const handleContextMenu = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('a')) return
    onContextMenu(e)
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className="track-row"
      onClick={handleRowClick}
      onContextMenu={handleContextMenu}
    >
      <span className="sr-only">{escapeHtml(title)}</span>
      <div className="track-info" style={{ flex: 1, minWidth: 0 }}>
        <div className="track-title">{escapeHtml(title)}</div>
        <div className="track-sub">{escapeHtml(artist)} • {escapeHtml(album)}</div>
      </div>
      <div className="track-duration numeric">{durationStr}</div>
      {showPlaylistColumn && (
        <div className="track-playlists membership">
          {memberships.length > 0 ? memberships.join(', ') : '–'}
        </div>
      )}
      {url && (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="btn small"
        >
          bot url
        </a>
      )}
    </div>
  )
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
