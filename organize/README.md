# organize tools

These utilities restructure the beets crate into proper albums and singles, fixing how beets splits by track artist vs album artist and scattered whole albums as singletons.

## cleanup
```bash
uv run python -m organize.cleanup                     # dry-run: print plan, move nothing
uv run python -m organize.cleanup --apply             # move files + write albumartist tags
uv run python -m organize.cleanup --apply --rebuild-db # ...then rebuild beets.db from the reorganized crate
uv run python -m organize.cleanup --verbose           # print every planned move
uv run python -m organize.cleanup --crate /path/to/crate
```

The regrouper works straight off file tags (`mediafile`), independent of beets:
  - Groups every audio file in `<crate>/albums` and `<crate>/singles` by its album tag
  - >=2 files share an album  → one album folder, named `<albumartist> - <album>`
  - Exactly 1 file per album   → singleton in `<crate>/singles>/<artist> - <title>`
  - No album tag               → singleton (a file with no album isn't an album)
  - Canonical albumartist per group = the dominant artist string across the group's files (collab variants "A & B"/"A & C" collapse to "A" when A is the majority); fall back to the dominant primary collaborator; else "Various Artists" (a true VA compilation like "'SLOWED' EDITS VOL. I")
  - Writes the canonical albumartist tag into every album-group file so a future beets as-is re-import won't re-split them
  - Skiptags non-audio files (beets.db, *.log, library.csv, cover art, .nomedia)

Idempotent: re-running on an already-clean crate is a no-op.

## preimport
```bash
uv run python -m organize.preimport                       # dry-run: print plan
uv run python -m organize.preimport --apply               # stage + write tags
uv run python -m organize.preimport --apply --verbose     # print every move
uv run python -m organize.preimport --no-merge-existing   # new folders only
uv run python -m organize.preimport -i /path -o /crate
```

Stands between loose-track downloads and beets import, staging every incoming group into proper `<input>/albums/Artist - Album/` and writing a canonical albumartist. Uses existing `<crate>/albums` to decide whether to merge or stage a new folder. Prevents beets' album pass from splitting collab tracks and singles pass from getting true albums.

## beets_import
```bash
uv run python -m organize.beets_import -i <input> -o <output>
uv run python -m organize.beets_import -i <input> -o <output> --dry-run
uv run python -m organize.beets_import -i <input> -o <output> --pass albums   # or --pass singles
uv run python -m organize.beets_import --export-csv                             # dump library to csv
```

Two-pass beets importer that matches tracks against MusicBrainz for albums then treats remaining loose tracks as singletons. Works with staged `<input>/albums/` subfolders (from preimport) so one-folder-per-album grouping instead of a flat album.

The `normalize_artists` beets plugin (`organize/normalize_artists.py`) rewrites artist strings to a consistent `"A, B & C"` form at import (handles `feat.`/`ft.`, collab `x`, `and`). Enable it via `config.yaml`'s `plugins` list + `pluginpath`.

## normalize_artists
```bash
uv run python -m organize.normalize_artists
```

Runs the built-in test suite for the normalize_artists plugin. Tests cover track artist→albumartist normalizations (collabs, features, various), artist name standardization, and edge cases. Expects "all tests passed" to succeed.

## environment variables
Set in `.env` (see `.env.example`):
- `ARCHIVE_PATH` - library root (default: `~/music/tapebuilding`)
- `FFMPEG_PATH` - ffmpeg executable if not on `PATH`
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_USER_ID` - Spotify API credentials
- `SPOTIFY_REDIRECT_URI` - OAuth redirect (default: `http://127.0.0.1:8888/callback`)
- `FIREBASE_PROJECT_ID`, `FIREBASE_CREDENTIALS_PATH` - for soundbyte album export (`download/soundbyte_albums.py`)

## config
Beets requires a `config.yaml` in the crate root. Use `organize/config.yaml.example` as a starting template:
```bash
cp organize/config.yaml.example organize/config.yaml
uv run python -m organize.cleanup --apply
```

The example includes all required sections for the organize tools: pluginpath, paths, import settings, match preferences, plugins list (including normalize_artists), and fetchart/embedart configuration.