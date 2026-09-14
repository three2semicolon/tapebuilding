# tapebuilding

building and managing my personal music library.

## overview

five commands, one per package:

- `core` - opinionated multi-step workflows stitching the others together (download + import + refresh in one pass, or a full sync)
- `download` - export spotify playlists/liked songs, download from spotify/soundcloud/youtube, retry failures, pull soundbyte albums
- `organize` - turn raw downloads into a clean beets-managed crate
- `playlists` - rebuild local `.m3u8`s from spotify playlists, matched against the crate
- `tapedeck` - mirror a rotation subset of the crate to a synced device

each package owns its own `cli.py`; nothing below the cli layer calls
`sys.exit()` or assumes it's being run from a terminal, so all of this is
also directly importable (see `PACKAGE_OVERVIEW.md`).

## install

```bash
git clone <repository-url>
cd tapebuilding
uv sync
```

installs `core`, `download`, `organize`, `playlists`, and `tapedeck` as
console commands, editable.

## core - multi-step workflows

### download-songs

download -> beets-import -> playlists-refresh, in one pass.

```bash
core download-songs "<spotify-url>"                     # dry run by default
core download-songs "<spotify-url>" --apply
core download-songs path/to/urls.txt --apply
core download-songs --apply --only download --only import   # repeatable, runs in fixed order regardless
```

options:

- `--apply` - do it for real (default: dry run)
- `--archive-path` - crate root override (default `ARCHIVE_PATH`)
- `-i, --input` - staging drop for downloads (default `<crate>/unorganized`)
- `--only` - run only this step (repeatable: `download`, `import`, `playlists`); default all three, in order
- `--format` (default mp3), `--bitrate` (default 320k)
- `--verbose` - forwarded to each step (maps to spotdl/yt-dlp's `--debug` for the download step)

dry run doesn't skip the steps - each one runs for real in its own no-op
mode instead (download does a real existence check without downloading,
import runs beets `--pretend`, playlists previews without writing). that's
a deliberate change from the old subprocess-based pipeline, which printed
the would-be command and ran nothing at all.

### sync

rescrape spotify + rebuild every (or named) playlist's `.m3u8`. the
`playlists --apply --rescrape` flow, promoted to its own command.

```bash
core sync
core sync -p "<playlist-name-or-id>"       # repeatable
core sync --covers                          # also download each playlist's cover art
```

options:

- `-p, --playlist` - sync a specific playlist by name or spotify id (repeatable; default: all owned)
- `--covers` - download each playlist cover to `<name>.jpg`
- `--verbose` - print every match decision
- `--playlists-path`, `--archive-path`, `--exports-dir` - path overrides

no dry-run mode - a sync's whole point is writing the refreshed `.m3u8`s.

## download - export, download, retry, soundbyte

### export spotify data

```bash
download export                                  # all playlists + liked songs (default)
download export --mine                            # only your own playlists
download export -o /path/to/export               # custom output directory (default: PLAYLISTS_PATH/exports)
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

with two or more `-p`/`--playlists-file` identifiers, the export scopes to
just those playlists instead: `playlists_manifest.csv` +
`playlists_manifest_urls.txt`, separate filenames so they don't clobber
the full-library export.

### download music from spotify

downloads from spotify urls (tracks, albums, playlists) via spotdl.
`--url-file` accepts a `.txt` (one url per line), a `.csv` (must have a
`spotify_url` column), or a directory of `.csv` files.

```bash
download spotify                                            # <exports>/spotify_manifest_urls.txt
download spotify -u path/to/urls.txt
download spotify -u /path/to/export/directory -o /path/to/music
download spotify -u path/to/urls.txt --batch-size 25        # urls per spotdl call (default 1)
download spotify -u path/to/urls.txt --pre-skip-existing    # skip tracks already in the library (needs csv metadata)
download spotify -u path/to/urls.txt --validate-only        # check existence without downloading
```

options:

- `-f, --format` (default mp3), `-b, --bitrate` (default 320k)
- `--overwrite-errors` - re-download files that errored previously
- `--skip-existing` - pass `--skip-existing` through to spotdl
- `--retries` (default 3), `--retry-delay` (default 3s)
- `--cookies-from-browser` - browser to pull cookies from (e.g. `chrome`)
- `--cookie-file` - path to a Netscape-format `cookies.txt`; preferred over `--cookies-from-browser` (avoids the browser file-lock issue)
- `--debug` - DEBUG log level for spotdl/yt-dlp instead of INFO
- `-o, --output` - output directory (default: library root)

urls are deduplicated preserving first-seen order. spotdl's exit code is
unreliable - it returns 0 even when nothing downloads - so output is
scanned for soft/hard failure markers and logged to
`failed_downloads.txt` / `soft_failures.txt`.

### retry failed downloads

compiles `soft_failures.txt` + `failed_downloads.txt` into a single retry
list, filtered against what's already in the library so you only retry
what's still missing.

```bash
download retry                                             # retry_list.txt, drop unavailable, check vs library
download retry --include-unavailable                       # keep track_unavailable too
download retry --no-check                                   # combine + dedupe without the library check
download retry --metadata-source <export-dir-or-csv> --library-root <music-root>
download retry --report-csv manual_hunt.csv                 # named + sorted manual-hunt sheet (see below)
download retry -o retry_list.txt
```

urls are deduped across and within both files (a track can fail soft, then
hard, many times); reasons are unioned per url. `track_unavailable` (hard)
is excluded by default - those tracks are gone. the existence check reuses
`spotify`'s exact matching path (export csv metadata -> predicted spotdl
filename -> normalized library index), so `retry_list.txt` is consistent
with what `spotify --pre-skip-existing` would itself skip.

typical flow: run `download spotify -u retry_list.txt`, then re-run
`download retry` - the library check drops whatever the retry round just
succeeded on, so the next `retry_list.txt` is only what's still missing.

`--report-csv` writes the remaining tracks to a manual-hunt sheet - one
row per still-missing track with `artist, track, album, reason, spotify_url, search` (the `search` column is a clickable youtube results
link), sorted by artist -> album -> track. needs the same export csvs as
the existence check (names come from there).

### download from yt-dlp

downloads a single track, set/playlist, or album from any
yt-dlp-supported url (soundcloud, youtube, etc.) via yt-dlp. takes one url
directly - yt-dlp walks a playlist/set itself.

```bash
download ytdl "https://soundcloud.com/artist/track"
download ytdl "https://soundcloud.com/artist/sets/my-set"     # set -> "Set Name/NN - Uploader - Title.ext"
download ytdl -o /path/to/music "https://..."                 # custom output (default: ARCHIVE_PATH)
download ytdl -f best "https://..."                           # keep original container, no transcode
download ytdl -m "https://soundcloud.com/artist/sets/my-set"  # list tracks without downloading
```

options:

- `-o, --output` - output directory (default: `ARCHIVE_PATH`)
- `-f, --format` - `mp3` (default), or another format from the supported set, or `best` (no transcode)
- `--quality` - ffmpeg audio quality, 0 (best VBR) by default
- `--no-thumbnail` - don't embed cover art
- `--overwrite` - re-download existing files (default: skip)
- `-v, --verbose`
- `--metadata-only` - list tracks without downloading
- `--cookies-from-browser` - browser to read cookies from; needed for go+/restricted tracks on soundcloud and other sources
- `--ffmpeg` - ffmpeg executable path, overriding `FFMPEG_PATH`

filenames follow `Uploader - Title.ext` (singles) or `Set Name/NN - Uploader - Title.ext` (sets/albums), so they sit alongside spotdl
downloads in the same library root. yt-dlp's metadata is sparser than
spotdl's - you reliably get uploader, title, duration, cover, but usually
not album/track number/release date (varies by source; soundcloud sets
include them).

### soundbyte album pulls

pulls top-N albums from a firebase firestore collection (a separate
personal project), matches them on spotify, and exports a track-level
manifest `download spotify` can consume.

```bash
download soundbyte
download soundbyte --limit 50
download soundbyte -o /path/to/export --delay 0.5
```

options:

- `--limit` - how many top-ranked albums to pull (default 200)
- `-o, --output` - output directory for csvs (default `PLAYLISTS_PATH/exports`)
- `--delay` - delay between spotify api calls, in seconds (default 0.3)

writes `soundbyte_albums.csv`/`soundbyte_album_urls.txt` (album-level) and
`soundbyte_tracks.csv`/`soundbyte_track_urls.txt` (track-level, expanded
from matched albums, same column shape as `spotify_manifest.csv` so
`download spotify --pre-skip-existing -u soundbyte_tracks.csv` works
directly). requires `firebase-admin` and `FIREBASE_PROJECT_ID` +
`FIREBASE_CREDENTIALS_PATH` in `.env`.

## organize - beets import + crate cleanup

two-pass beets importer: pass 1 groups multi-track albums and matches
against musicbrainz; pass 2 imports remaining loose tracks as singletons.
runs a pre-import staging pass automatically (regroups the drop into one
folder per album before beets ever sees it) unless `--no-preimport`.

```bash
organize import -i <crate>/unorganized -o <crate>
organize import -i ... -o ... --dry-run
organize import -i ... -o ... --pass albums   # album pass only
organize import -i ... -o ... --pass singles  # singles pass only
organize import --export-csv                   # dump library to csv
```

`ARCHIVE_PATH` (or `-o`) is required here, no fallback - this command
moves files and rewrites tags, so a missing crate root is a hard error
rather than a guessed directory.

also handles regrouping an **already-imported** crate that ended up with
per-track-artist album splits or scattered singletons (the two failure
modes beets' own importer is prone to on this library):

```bash
organize cleanup                        # dry-run: print plan, move nothing
organize cleanup --apply                # move files + write albumartist tags
organize cleanup --apply --rebuild-db   # ...then rebuild beets.db from the reorganized crate
organize cleanup --verbose              # print every planned move
organize cleanup --crate /path/to/crate
```

idempotent - re-running on an already-clean crate is a no-op. flags
plausible wrong-merges (unusually large album groups) and VA-filed albums
in the dry-run summary for manual review.

the `normalize_artists` beets plugin rewrites artist strings to a
consistent `"A, B & C"` form at import (handles `feat.`/`ft.`, collab `x`,
`and`); enabled via `organize/config.yaml`'s `plugins` list +
`pluginpath`.

## playlists - rebuild local playlists from spotify

rescrapes spotify (optionally scoped to specific playlists) and rebuilds
each owned playlist's `.m3u8` against the crate, using the same tiered
matcher as `tapedeck`. writes unmatched tracks to `unmatched.csv` /
`unmatched_urls.txt` (feeds back into `download spotify -u`) rather than
failing the run. `--covers` downloads each playlist's cover art.

`core sync` is this command's `--apply --rescrape` flow, promoted to its
own entry point - see above for that usage. for the full `playlists`
flag set (dry-run/preview mode, `-p`/`--all`/`--mine` selection, etc.)
run `playlists --help`.

## tapedeck - mirror a rotation subset to a synced device

loads/unloads/lists a subset of the crate - albums, songs, soundtracks,
or whole playlists - mirrored 1:1 by crate-relative path into
`TAPEDECK_PATH`, for offline/roaming playback on another device. no
downloading, no spotify involved; copies (or hardlinks, same-volume only)
files that already exist in the crate. dry-run by default, matching the
rest of the repo's `--apply` convention. unloading a playlist only
removes a track if no other loaded playlist still references it
(refcounted; doesn't know about tracks separately loaded via `load album`/`load song`).

```bash
tapedeck load ...
tapedeck unload ...
tapedeck list
```

for the full `load`/`unload`/`list` flag set (kind/spec syntax,
`--apply`, `--link`, `--overwrite`, `--verbose`) run `tapedeck --help`.

## environment variables

set in `.env` (see `.env.example`). uppercase only - the old dual-case
fallback (`ARCHIVE_PATH`/`archive_path`) has been dropped.

- `ARCHIVE_PATH` - crate root. has a `~/music/tapebuilding` convenience
  default almost everywhere, **except** `organize import`/`organize cleanup`, which require it explicitly (no fallback) since both move
  files on disk.
- `PLAYLISTS_PATH` - where `.m3u8`s + exports live. required, no
  fallback.
- `TAPEDECK_PATH` - sync target for `tapedeck`. defaults to
  `~/music/tapedeck`.
- `FFMPEG_PATH` - ffmpeg executable, if not already on `PATH`.
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` - spotify api creds.
- `SPOTIFY_REDIRECT_URI` - oauth redirect (default
  `http://127.0.0.1:8888/callback`).
- `FIREBASE_PROJECT_ID`, `FIREBASE_CREDENTIALS_PATH` - for `download soundbyte`.
