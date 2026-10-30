---
icon: lucide/arrow-down
---

# download

export, download, retry, and soundbyte album pulls.

## export spotify data

```bash
download export                                  # all playlists + liked songs (default)
download export --mine                            # only your own playlists
download export -o /path/to/export               # custom output directory
download export -p "<playlist-url-or-id>"        # a single playlist
download export -p "<url-1>" -p "<url-2>"        # two or more -> exported + merged into a scoped playlists_manifest.csv
download export --playlists-file playlists.txt   # newline-delimited list of urls/ids (#-comments ignored), combined with -p
```

outputs (in the export directory):

- `playlists.csv` - playlist metadata
- `playlist_tracks.csv` - all playlist tracks (with cross-playlist duplicates)
- `liked_songs.csv` - saved tracks
- `spotify_manifest.csv` - deduplicated master track list (fuzzy match collapses remasters/regional versions, keeping the most popular)
- `spotify_manifest_urls.txt` - track urls, one per line, for `download spotify`

with two or more `-p`/`--playlists-file` identifiers, the export scopes to just those playlists instead: `playlists_manifest.csv` + `playlists_manifest_urls.txt`, separate filenames so they don't clobber the full-library export.

## download music from spotify

downloads from spotify urls (tracks, albums, playlists) via spotdl.

```bash
download spotify "https://open.spotify.com/track/..."       # download a single spotify url directly
download spotify                                            # <exports>/spotify_manifest_urls.txt
download spotify -u path/to/urls.txt
download spotify -u /path/to/export/directory -o /path/to/music
download spotify -u path/to/urls.txt --batch-size 25
download spotify -u path/to/urls.txt --pre-skip-existing
download spotify -u path/to/urls.txt --validate-only
```

## download music from soundcloud

downloads from soundcloud urls (tracks, sets) via yt-dlp.

```bash
download soundcloud "https://soundcloud.com/artist/track"
download soundcloud "https://soundcloud.com/artist/sets/my-set"
download soundcloud -u path/to/urls.txt
```

## download from yt-dlp

downloads a single track, set/playlist, or album from any yt-dlp-supported url.

```bash
download ytdl "https://soundcloud.com/artist/track"
download ytdl -o /path/to/music "https://..."
download ytdl -f best "https://..."
download ytdl -m "https://soundcloud.com/artist/sets/my-set"  # list tracks without downloading
```

## retry failed downloads

compiles `soft_failures.txt` + `failed_downloads.txt` into a single retry list, filtered against what's already in the library.

```bash
download retry                                             # retry_list.txt, drop unavailable, check vs library
download retry --include-unavailable
download retry --no-check
download retry --report-csv manual_hunt.csv
```

## soundbyte album pulls

pulls top-n albums from a firebase firestore collection, matches them on spotify, and exports a track-level manifest `download spotify` can consume.

```bash
download soundbyte
download soundbyte --limit 50
download soundbyte -o /path/to/export --delay 0.5
```

requires `firebase-admin`, `firebase_project_id` + `firebase_credentials_path` in `.env`.
