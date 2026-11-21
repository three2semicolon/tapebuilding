/**
 * CoverImage - playlist cover art with a fallback placeholder.
 */

import type { Playlist } from '@/services/api'

interface CoverImageProps {
  playlist: Pick<Playlist, 'kind' | 'cover'>
  size?: number
}

export function CoverImage({ playlist, size = 170 }: CoverImageProps) {
  return (
    <div
      className="cover"
      style={{ width: size, height: size }}
    >
      {playlist.cover ? (
        <img
          src={playlist.cover}
          alt="cover"
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />
      ) : (
        <span className="cover-placeholder">
          {playlist.kind === 'synced' ? '♫'
            : playlist.kind === 'detached' ? '⏸'
            : '●'}
        </span>
      )}
    </div>
  )
}
