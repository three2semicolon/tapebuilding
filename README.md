# tapebuilding

building and managing my personal music library.

## overview

tools:

- export spotify playlists and liked songs to csv
- download music from spotify urls via spotdl
- download from soundcloud, youtube, etc. via yt-dlp
- organize downloads with beets

## install

```bash
git clone <repository-url>
cd tapebuilding
uv sync
```

installs the `export`, `spotify`, and `ytdl` commands in editable mode.

## export spotify data

```bash
export                                  # all playlists + liked songs (default)
export --mine                            # only your own playlists
export -o /path/to/export               # custom output directory
export -p "<playlist-url-or-id>"        # a single playlist
```

outputs (in the export directory):

- `playlists.csv` - playlist metadata
- `playlist_tracks.csv` - all playlist tracks (with cross-playlist duplicates)
- `liked_songs.csv` - saved tracks
- `spotify_manifest.csv` - deduplicated master track list (fuzzy match collapses remasters/regional versions, keeping the most popular)
- `spotify_manifest_urls.txt` - track urls, one per line, for `spotify`

## download music from spotify

downloads from spotify urls (tracks, albums, playlists) via spotdl. `--url-file` accepts a `.txt` (one url per line), a `.csv` (must have a `spotify_url` column), or a directory of `.csv` files.

```bash
spotify                                            # export/spotify_manifest_urls.txt
spotify -u path/to/urls.txt
spotify -u /path/to/export/directory -o /path/to/music
spotify -u path/to/urls.txt --batch-size 25        # urls per spotdl call (default 1)
spotify -u path/to/urls.txt --pre-skip-existing    # skip tracks already in the library (needs csv metadata)
spotify -u path/to/urls.txt --validate-only        # check existence without downloading
```

options:

- `--format` (default mp3), `--bitrate` (default 320k)
- `--overwrite-errors` - re-download files that errored previously
- `--skip-existing` - pass `--skip-existing` through to spotdl
- `--verbose` - verbose spotdl output
- `-o, --output` - output directory (default: library root)

urls are deduplicated preserving first-seen order. spotdl's exit code is unreliable - it returns 0 even when nothing downloads - so output is scanned for soft/hard failure markers and logged to `failed_downloads.txt` / `soft_failures.txt`.

## retry failed downloads

compiles `soft_failures.txt` + `failed_downloads.txt` into a single `retry_list.txt` of bare urls (one per line, ready for `spotify -u`), filtered against what's already in the library so you only retry what's still missing.

```bash
retry                                             # retry_list.txt, drop unavailable, check vs library
retry --include-unavailable                       # keep track_unavailable too
retry --no-check                                   # combine + dedupe without the library check
retry --metadata <export-dir-or-csv> --library <music-root>
retry --report-csv manual_hunt.csv                 # named + sorted manual-hunt sheet (see below)
retry -o retry_list.txt -v                         # custom output + print grouped breakdown
```

urls are deduped across and within both files (a track can fail soft, then hard, many times); reasons are unioned per url. `track_unavailable` (hard) is excluded by default - those tracks are gone. the existence check reuses `spotify`'s exact matching path (export CSV metadata → predicted spotDL filename → normalized library index), so `retry_list.txt` is consistent with what `spotify --pre-skip-existing` would itself skip. falls back to combining everything if the export CSVs aren't found; pass `--metadata` to point at them (needs CSVs with `track_name` + `artist_names` columns).

typical flow: run `spotify -u retry_list.txt`, then re-run `retry` - the library check drops whatever the retry round just succeeded on, so the next `retry_list.txt` is only what's still missing.

output categories (`-v` shows the urls): already on disk (skipped), no metadata (kept - can't predict a filename, spotDL re-checks), hard excluded, and the retry list. then: `spotify -u retry_list.txt`.

`--report-csv` writes the remaining tracks to a manual-hunt sheet - one row per still-missing track with `artist, track, album, reason, spotify_url, search` (the `search` column is a clickable YouTube results link), sorted by artist → album → track so you can source them by hand. needs the same export CSVs as the existence check (names come from there).

## download from yt-dlp

downloads a single track, set/playlist, or album from any yt-dlp-supported url (soundcloud, youtube, etc.) via yt-dlp. takes one url directly - yt-dlp walks a playlist/set itself.

```bash
ytdl "https://soundcloud.com/artist/track"
ytdl "https://soundcloud.com/artist/sets/my-set"     # set → "Set Name/NN - Uploader - Title.ext"
ytdl -o /path/to/music "https://..."                 # custom output (default: library root)
ytdl -f best "https://..."                           # keep original container, no transcode
ytdl -m "https://soundcloud.com/artist/sets/my-set"  # list tracks without downloading
```

options:

- `-o, --output` - output directory (default: library root)
- `-f, --format` - `mp3` (default), `m4a`, `opus`, `vorbis`, `wav`, `flac`, `alac`, `aac`, or `best` (no transcode)
- `-q, --audio-quality` - 0 (best) to 10 (worst), default 0
- `--no-thumbnail` - don't embed cover art
- `--overwrite` - re-download existing files (default: skip)
- `-v, --verbose` - verbose yt-dlp output
- `-m, --metadata-only` - list tracks without downloading
- `--cookies-from-browser` - browser to read cookies from (e.g. `chrome`); needed for go+ / restricted tracks on soundcloud and other sources
- `--ffmpeg` - ffmpeg path (default: `ffmpeg_path` env var, then system path)

filenames follow `Uploader - Title.ext` (singles) or `Set Name/NN - Uploader - Title.ext` (sets/albums), so they sit alongside spotdl downloads in the same library root. yt-dlp's metadata is sparser than spotdl's - you reliably get uploader, title, duration, cover, but usually not album/track number/release date (varies by source; soundcloud sets include them).

## organize with beets

two-pass beets importer (`organize/beets_import.py`): pass 1 imports multi-track albums to `albums/Artist - Album/`, pass 2 imports remaining loose tracks as singletons to `singles/Artist - Title`.

```bash
uv run python -m organize.beets_import -i <input> -o <output>
uv run python -m organize.beets_import -i <input> -o <output> --dry-run
uv run python -m organize.beets_import -i <input> -o <output> --pass albums   # or --pass singles
uv run python -m organize.beets_import --export-csv                             # dump library to csv
```

the `normalize_artists` beets plugin (`organize/normalize_artists.py`) rewrites artist strings to a consistent `"A, B & C"` form at import (handles `feat.`/`ft.`, collab `x`, `and`). enable it via `config.yaml`'s `plugins` list + `pluginpath`.

## environment variables

set in `.env` (see `.env.example`):

- `archive_path` - default download/library root (default `~/music/tapebuilding`)
- `ffmpeg_path` - ffmpeg executable if not on `PATH`
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_USER_ID` - spotify api creds
- `SPOTIFY_REDIRECT_URI` - oauth redirect (default `http://127.0.0.1:8888/callback`)
- `FIREBASE_PROJECT_ID`, `FIREBASE_CREDENTIALS_PATH` - for the soundbyte album export (`download/soundbyte_albums.py`)
