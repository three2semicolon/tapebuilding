/**
 * AudioPlayer - inline audio player using the /files/ endpoint.
 * Accepts a track path and renders standard HTML5 audio controls.
 */

import { useEffect, useState } from 'react'

interface AudioPlayerProps {
  /** Track path (relative to crate root) to play. Null = no track. */
  srcPath: string | null
  title: string
  artist: string
}

export function AudioPlayer({ srcPath, title, artist }: AudioPlayerProps) {
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!srcPath) {
      setUrl(null)
      return
    }
    const u = `/files/${encodeURIComponent(srcPath)}`
    setUrl(u)
  }, [srcPath])

  return (
    <div className="audio-player">
      <div className="audio-player-bar">
        <div className="audio-player-info">
          <div className="audio-player-title">{title}</div>
          <div className="audio-player-artist">{artist}</div>
        </div>
        {url ? (
          <audio
            src={url}
            controls
            autoPlay
            style={{ width: '100%', height: 36 }}
          />
        ) : null}
      </div>
    </div>
  )
}
