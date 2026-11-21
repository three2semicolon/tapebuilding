/**
 * PlaylistCard - individual playlist shown in the sidebar grid.
 */

import type { Playlist } from '@/services/api'
import { CoverImage } from './CoverImage'

interface PlaylistCardProps {
  playlist: Playlist
  onClick: (name: string) => void
  onDelete?: (name: string, e: React.MouseEvent) => void
  selected?: boolean
}

export function PlaylistCard({ playlist, onClick, onDelete, selected = false }: PlaylistCardProps) {
  const kindLabel = playlist.kind === 'synced' ? 'synced'
    : playlist.kind === 'detached' ? 'detached'
    : 'local'

  return (
    <div
      className={`playlist-card ${selected ? 'selected' : ''}`}
      onClick={() => onClick(playlist.name)}
    >
      <CoverImage playlist={playlist} />
      <div className="name" title={playlist.name}>
        {playlist.name}
      </div>
      <div className="meta">
        <span className={`tag ${kindLabel}`}>{kindLabel}</span>
        <br />
        {playlist.count} track{(playlist.count !== 1 ? 's' : '')}
        {playlist.edited && <span className="tag warn">edited</span>}
      </div>
      {onDelete && (
        <button
          className="btn small danger"
          onClick={(e) => {
            e.stopPropagation()
            onDelete(playlist.name, e)
          }}
        >
          delete
        </button>
      )}
    </div>
  )
}
