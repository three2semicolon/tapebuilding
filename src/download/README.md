# download tools

These utilities gather and prepare audio files from external sources. Each focuses on a specific platform or workflow concern. Use `uv run <name>` to run a tool.

## export (spotify)
```bash
export                                    # all playlists + liked songs (default)
export --mine                              # only your own playlists
export -o /path/to/export                  # custom output directory
export -p "<playlist-url-or-id>"          # a single playlist
```
Creates structured CSV exports for downstream processing:
- `playlists.csv` - playlist metadata
- `playlist_tracks.csv` - all playlist tracks (with cross-playlist duplicates)
- `liked_songs.csv` - saved tracks
- `spotify_manifest.csv` - deduplicated master track list (fuzzy match collapses remasters/regional versions, keeping most popular)
- `spotify_manifest_urls.txt` - track URLs, one per line, ready for `spotify -u`

## spotify
```bash
spotify                                            # process spotify_manifest_urls.txt
spotify -u path/to/urls.txt
spotify -u /path/to/export/directory -o /path/to/music
spotify -u path/to/urls.txt --batch-size 25        # URLs per spotdl call (default 1)
spotify -u path/to/urls.txt --pre-skip-existing    # skip tracks already in the library (needs csv metadata)
spotify -u path/to/urls.txt --validate-only        # check existence without downloading
```
Downloads music from Spotify (track, album, playlist) via spotdl. Accepts `.txt` (one URL per line), `.csv` (must have a `spotify_url` column), or directories of `.csv` files.

Options:
- `--format` (default: `mp3`), `--bitrate` (default: `320k`)
- `--overwrite-errors` - re-download files that errored previously
- `--skip-existing` - pass `--skip-existing` through to spotdl
- `--verbose` - verbose spotdl output
- `-o, --output` - output directory (default: library root)

URLs are deduplicated preserving first-seen order. spotdl's exit code is unreliable - it returns 0 even when nothing downloads - so output is scanned for soft/hard failure markers and logged to `failed_downloads.txt` / `soft_failures.txt`.

## ytdl
```bash
ytdl "https://soundcloud.com/artist/track"
ytdl "https://soundcloud.com/artist/sets/my-set"     # set → "Set Name/NN - Uploader - Title.ext"
ytdl -o /path/to/music "https://..."                 # custom output (default: library root)
ytdl -f best "https://..."                           # keep original container, no transcode
ytdl -m "https://soundcloud.com/artist/sets/my-set"  # list tracks without downloading
```
Downloads a single track, set/playlist, or album from any yt-dlp-supported URL (SoundCloud, YouTube, etc.) via yt-dlp. yt-dlp walks a playlist/set itself. Takes one URL directly.

Options:
- `-o, --output` - output directory (default: library root)
- `-f, --format` - `mp3` (default), `m4a`, `opus`, `vorbis`, `wav`, `flac`, `alac`, `aac`, or `best` (no transcode)
- `-q, --audio-quality` - 0 (best) to 10 (worst), default 0
- `--no-thumbnail` - don't embed cover art
- `--overwrite` - re-download existing files (default: skip)
- `-v, --verbose` - verbose yt-dlp output
- `-m, --metadata-only` - list tracks without downloading
- `--cookies-from-browser` - browser to read cookies from (e.g., `chrome`); needed for go+ / restricted tracks on SoundCloud and other sources
- `--ffmpeg` - ffmpeg path (default: `ffmpeg_path` env var, then system path)

Filenames follow `Uploader - Title.ext` (singles) or `Set Name/NN - Uploader - Title.ext` (sets/albums), so they sit alongside spotdl downloads in the same library root. yt-dlp's metadata is sparser than spotdl's - you reliably get uploader, title, duration, cover, but usually not album/track number/release date (varies by source; SoundCloud sets include them).

## retry
```bash
retry                                             # retry_list.txt, drop unavailable, check vs library
retry --include-unavailable                       # keep track_unavailable too
retry --no-check                                   # combine + dedupe without the library check
retry --metadata <export-dir-or-csv> --library <music-root>
retry --report-csv manual_hunt.csv                 # named + sorted manual-hunt sheet (see below)
retry -o retry_list.txt -v                         # custom output + print grouped breakdown
```
Resumes failed downloads by compiling `soft_failures.txt` + `failed_downloads.txt` into a single `retry_list.txt` of bare URLs ready for `spotify -u`, filtered against what's already in the library.

Retries deduplicate across and within both files (a track can fail soft, then hard, many times); reasons are unioned per URL. `track_unavailable` (hard) is excluded by default - those tracks are gone. The existence check reuses `spotify`'s exact matching path (export CSV metadata → predicted spotDL filename → normalized library index), so `retry_list.txt` is consistent with what `spotify --pre-skip-existing` would itself skip.

Typical flow: run `spotify -u retry_list.txt`, then re-run `retry` - the library check drops whatever the retry round just succeeded on, so the next `retry_list.txt` is only what's still missing.

`-v` shows URLs and categorizes output by: already on disk (skipped), no metadata (kept - can't predict a filename, spotDL re-checks), hard excluded, and the retry list.

`--report-csv` writes remaining tracks to a manual-hunt sheet - one row per still-missing track with `artist, track, album, reason, spotify_url, search` (the `search` column is a clickable YouTube results link), sorted by artist → album → track so you can source them by hand.

## soundbyte
```bash
soundbyte -p <playlist-url>           # export a spotify playlist or liked songs as a firebase firestore album (soundbyte side)
soundbyte -m <manifest-url>          # export a spotify playlist or liked songs as a firebase firestore album (spotify side)
soundbyte -b <export-dir> -p <playlist-url>     # batch process a series of spotify playlists (use -r for resume on the same playlist name)
```
Exports Spotify data to Firebase Firestore for album management, enabling use with the soundbyte app's album management workflow.

Requires:
- Firebase project credentials (see `.env.example`)
- Spotify API credentials (see `.env.example`)

## environment variables
Set in `.env` (see `.env.example`):
- `ARCHIVE_PATH` - default download/library root (default: `~/music/tapebuilding`)
- `FFMPEG_PATH` - ffmpeg executable if not on `PATH`
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_USER_ID` - Spotify API credentials
- `SPOTIFY_REDIRECT_URI` - OAuth redirect (default: `http://127.0.0.1:8888/callback`)
- `FIREBASE_PROJECT_ID`, `FIREBASE_CREDENTIALS_PATH` - for the soundbyte album export (`download/soundbyte_albums.py`)