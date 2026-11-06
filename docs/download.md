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

## export soundcloud data

expose soundcloud sets/likes to csv for `download soundcloud`.

```bash
download export --service soundcloud --type all-sets         # all sets for soundcloud_user (default: "me")
download export --service soundcloud --type likes             # all liked tracks for soundcloud_user
download export --service soundcloud --type sets --set-ids "<set-url>"   # export a specific set
download export --service soundcloud --type sets --playlists-file sets.txt  # newline-delimited set urls/ids (#-comments ignored)
download export --service soundcloud --type sets -p "<url-1>" -p "<url-2>"  # two or more sets, combined
```

outputs (in `<exports>/soundcloud/`):

- `soundcloud_manifest.csv` - deduplicated master track list (track url as primary key)
- `soundcloud_manifest_urls.txt` - track urls, one per line, for `download soundcloud`
- `playlists.csv` / `playlist_tracks.csv` - playlist-format files for the `playlists` command
- `likes.csv` / `likes_urls.txt` - liked tracks (with `--type likes`)

with `--type sets` and `--playlists-file` / `--set-ids`, the export scopes to just those sets instead of all.

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
download soundcloud "https://soundcloud.com/artist/sets/my-set"     # set -> "Set Name/NN - Uploader - Title.ext"
download soundcloud -u path/to/urls.txt
download soundcloud -u path/to/urls.txt --manual                   # prompt for each track's source (youtube url or local file)
download soundcloud -u path/to/urls.txt --batch-size 25            # urls per yt-dlp call (default 1)
download soundcloud -u path/to/urls.txt --pre-skip-existing        # skip tracks already in the library (needs csv metadata)
download soundcloud -u path/to/urls.txt --validate-only            # check existence without downloading
```

options:

- `-u, --url-file` - path to file containing urls (default: `soundcloud_manifest_urls.txt`)
- `-f, --format` (default mp3), `-b, --bitrate` (default 320k)
- `--overwrite-errors` - re-download files that errored previously
- `--skip-existing` - pass `--skip-existing` through to yt-dlp
- `--retries` (default 3), `--retry-delay` (default 3s)
- `--cookies-from-browser` - browser to pull cookies from (e.g. `chrome`)
- `--cookie-file` - path to a Netscape-format `cookies.txt`; preferred over `--cookies-from-browser` (avoids the browser file-lock issue)
- `--debug` - DEBUG log level for yt-dlp instead of INFO
- `--manual` - skip primary download, prompt for each track's fallback source (enter a youtube url or local file path; backspace marks as lost)
- `--soundcloud-fallback` / `--no-soundcloud-fallback` - prompt for youtube url or local file when yt-dlp fails (default: off)
- `-o, --output` - output directory (default: library root)
- `--clean` - run `organize validate --all` after successful download
- `--verbose` - verbose output

urls are deduplicated preserving first-seen order. output is
scanned for soft/hard failure markers and logged to
`failed_downloads.txt` / `soft_failures.txt`. soundcloud metadata uses
`uploader`/`title` keys and is translated to `artist`/`track` for fallback mode.

### lost songs

during manual mode (`--manual`), pressing backspace on a track marks it as lost: its row is appended to `lost-songs.csv` (next to `unmatched.csv`) and removed from `unmatched.csv`. on subsequent runs, both the spotify and soundcloud download entry points read `lost-songs.csv` and skip those urls so they aren't re-downloaded.

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
