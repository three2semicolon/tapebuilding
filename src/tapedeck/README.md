# tapedeck

A rotation subset of the crate, mirrored 1:1 by crate-relative path into
`TAPEDECK_PATH` so syncthing can push it to devices for offline/roaming playback.
The old hand-staged tape (`full_albums/`, a flattened `singles/`, one
`soundtracks/`) now lives under `TAPEDECK_PATH/old/`; new loads mirror the crate's
own subtree (`albums/`, `singles/`, `soundtracks/`, `playlists/`) and don't touch
`old/`.

No Spotify, no download — everything loaded here already lives in the crate
(`ARCHIVE_PATH`). The deck is just a copy (or hardlink) of a slice of it.

## the `tapedeck` command

```
uv run tapedeck load album "Captain Murphy - Duality Deluxe"        # preview (dry run)
uv run tapedeck load album "Captain Murphy - Duality Deluxe" --apply
uv run tapedeck load album "albums/Mick Jenkins - Or More; The Anxious" --apply   # path form, no index needed
uv run tapedeck load song "Halo" --apply --link                     # hardlink instead of copy
uv run tapedeck load soundtrack "sonic unleashed" --apply
uv run tapedeck load playlist "__mom" --apply
uv run tapedeck list
uv run tapedeck unload playlist "__mom" --apply
```

(load/unload take one `kind` and one or more `specs`; each subcommand is a dry run
unless `--apply`, matching every other CLI in this repo.)

## mirror-crate-exactly

Every staged file keeps its crate-relative path:

- `load album` → the whole folder `albums/<Artist - Album>/` (audio **and** the
  `cover.*` / `.pdf` siblings — a complete mirror).
- `load song` → the one file, *not* flattened: an album track stays at
  `albums/<Album>/NN - ….mp3`, a real single at `singles/Artist - Title.mp3`.
- `load soundtrack` → the whole matched subtree under `soundtracks/` at its real
  nesting.
- `load playlist` → the `.m3u8` copied **verbatim** to `playlists/<name>.m3u8`
  plus every track it references (each at its own crate-relative path).

Because `PLAYLISTS_PATH` lives *inside* the crate and `.m3u8`s reference tracks
with `../albums/…` paths relative to the m3u's own folder, a verbatim m3u8 copy
resolves identically under the tapedeck — no m3u rewriting.

## specs: path or name

A `SPEC` is a crate-relative path **or** a name, auto-detected:

- **path** — `albums/Captain Murphy - Duality Deluxe`, `singles/…`, a soundtrack
  dir, or a `.m3u8` path/filename. Fast and unambiguous; skips the crate index
  entirely. `load album "albums/Mick Jenkins - Or More; The Anxious"` needs no
  index.
- **name** — `Duality`, `Halo`, `sonic unleashed`, `__mom`. Resolved against:
  - album → folder basename under `albums/` first, then the index's `album` tag
    (catches a name that diverges from the folder). Multiple matches load all.
  - song → the crate index (norm(title), optionally narrowed by `Artist - Title`).
  - soundtrack → dir basename under `soundtracks/` (no index).
  - playlist → `.m3u8` filename under `playlists/` (no index).

Name loads that need the index build it on demand (cached at
`PLAYLISTS_PATH/exports/.playlist_index.jsonl`); `--reindex` forces a rebuild.

## unload

The inverse of load: remove the tapedeck mirror of each file the resolved spec
would have staged, then prune the now-empty parent dirs. Playlist unload is
refcounted — an audio file is removed only if no *other* `.m3u8` still staged under
`tapedeck/playlists/` references it, so two playlists sharing a track don't drop it
when one unloads. **The refcount is playlist-scope only** — it does *not* see
album/song loads. If a track on the deck is there both because a playlist references
it *and* because you `load album`-ed its parent independently, unloading the playlist
removes that track and punches a hole in the album copy (the deck doesn't track which
load staged a file). Avoid unloading a playlist whose tracks you also staged as part
of album/song loads, or re-load the album afterward. Always dry-run first.

## flags

- `--apply` — actually write/remove (default is a preview).
- `--link` — hardlink instead of copy (same volume only; saves space on `Y:`).
- `--overwrite` — replace an existing dst instead of skipping (load).
- `--reindex` — rebuild the cached crate index first (song/album-by-name).
- `--verbose` — print every file action.
- `--archive-path` / `--tapedeck-path` / `--playlists-path` — override the roots.

## env

Read from `.env` (dual-case, per the repo convention): `ARCHIVE_PATH` (the crate),
`TAPEDECK_PATH` (the deck), `PLAYLISTS_PATH` (the m3u8 source + exports dir, which
also hosts the cached index sidecar).

## planned

- a gui (web app) over load/list/unload.
- rotation/scheduling beyond manual load/unload.
