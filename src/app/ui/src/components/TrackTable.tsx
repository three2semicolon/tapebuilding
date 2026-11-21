/**
 * TrackTable - virtualized track table shared by library and playlist views.
 * Uses @tanstack/react-virtual for performant rendering and @dnd-kit for
 * drag-to-reorder within playlists. Selection is controlled via the `selected`
 * prop; checkbox/row clicks call `onSelectionChange` with the new path set.
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
import { useMemo, useRef, useState } from 'react'
import { type LibraryRow, type PlaylistEntry } from '@/services/api'

type TrackRow = LibraryRow | PlaylistEntry

interface TrackTableProps {
  tracks: TrackRow[]
  /** Externally controlled selection (array of paths). */
  selected?: string[]
  onRowClick?: (track: TrackRow) => void
  onSelectionChange?: (paths: string[]) => void
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
  onReorder,
  rowHeight = 32,
  overscan = 10,
  showPlaylistColumn = false,
  membership,
}: TrackTableProps) {
  const parentRef = useRef<HTMLDivElement>(null)
  const [internalSelected, setInternalSelected] = useState<Set<string>>(new Set())

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

  const handleSelectionChange = (paths: string[]) => {
    setInternalSelected(new Set(paths))
    onSelectionChange?.(paths)
  }

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
                onClick={() => {
                  const next = new Set(selectedSet)
                  if (next.has(path)) next.delete(path)
                  else next.add(path)
                  handleSelectionChange([...next])
                  onRowClick?.(track)
                }}
                onToggle={(p) => {
                  const next = new Set(selectedSet)
                  if (next.has(p)) next.delete(p)
                  else next.add(p)
                  handleSelectionChange([...next])
                }}
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
  onClick?: () => void
  onToggle?: (path: string) => void
  showPlaylistColumn: boolean
  memberships: string[]
}

function SortableTrackRow({
  track,
  index,
  virtualItem,
  isSelected,
  onClick,
  onToggle,
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

  const handleCheckboxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const path = track.path
    if (!path) return
    onToggle?.(path)
    e.stopPropagation()
  }

  const handleRowClick = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('input, a')) return
    onClick?.()
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className="track-row"
      onClick={handleRowClick}
    >
      <input
        type="checkbox"
        className="track-checkbox"
        checked={isSelected}
        onChange={handleCheckboxChange}
        style={{ marginRight: 8, flexShrink: 0 }}
      />
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
