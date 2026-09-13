# tapebuilding — package overview (pre-refactor snapshot)

This document describes what exists today: every package, every module, what
each one is meant to do, and what it actually does. It's the reference point
for the refactor plan (`REFACTOR_PLAN.md`) and the todo list (`TODO.md`).

The project builds and manages a personal music library: export Spotify data,
download from Spotify/SoundCloud/YouTube, organize into a beets-managed crate,
build local playlists, and mirror a rotation subset to a synced device. The
eventual goal is a local browser app on top of all of this, streaming out to
phone via Symfonium.

---

## download/

Acquisition layer. Exports Spotify metadata, downloads audio from Spotify
(via spotdl) and any yt-dlp-supported source, retries failures, and pulls a
curated album list from a Firebase-backed side project ("soundbyte").

### `spotify_to_csv.py` (cli: `export`)
Exports Spotify playlists + liked songs to CSV, and a deduplicated master
manifest of track URLs for the downloader.
- `export_all_data()` — full export: playlists.csv, playlist_tracks.csv,
  liked_songs.csv, spotify_manifest.csv (deduped), spotify_manifest_urls.txt.
- `export_specific_playlist()` — export one playlist by URL/ID.
- `extract_playlist_id_from_url()` — parses a playlist URL or spotify: URI to
  a bare ID. Also reused by `playlists/build.py`.
- `--mine` restricts to playlists the authenticated user owns.

### `spotify_utils.py`
Shared Spotify API helpers used by the export flow.
- `authenticate_spotify()` — user-auth flow (SpotifyOAuth, scopes for
  playlists/liked-songs/follows). Token cached to a bare relative path
  (`token_cache`) — not anchored to any config location.
- `get_user_playlists()`, `get_playlist_tracks()`, `get_liked_songs()` —
  paginated fetchers.
- `merge_and_deduplicate()` — two-pass dedup: exact by Spotify track ID, then
  fuzzy by normalized primary-artist + title (collapses remasters/regional
  versions), keeping the most popular track as canonical and merging playlist
  membership across collapsed duplicates.
- `_normalize_title()` / `_fuzzy_key()` — the fuzzy-key normalization used
  only by this dedup pass. Strips `feat.`/parenthetical content before the
  generic strip — a different (better) normalization than the generic
  lowercase-alphanumeric one used elsewhere.
- `export_to_csv()`, `export_manifest_as_txt()`, `get_export_dir()`.

### `download_spotify.py` (cli: `spotify`)
Downloads audio from Spotify URLs via spotdl, batched, with retry and
existence-checking.
- `download_spotify()` — main entry. Reads URLs from a `.txt`, `.csv` (needs
  `spotify_url` column), or directory of `.csv`s. Dedupes preserving order.
  Batches into spotdl subprocess calls. spotdl's exit code is unreliable (0
  even on failure), so stdout is scanned for hard-failure markers (track
  genuinely gone — `Track no longer exists`, `SongError`) and soft-failure
  markers (`AudioProviderError`, `LookupError`, etc.), each with its own
  retry/logging behavior. Failures logged to `failed_downloads.txt` /
  `soft_failures.txt`.
- `--pre-skip-existing` — predicts spotdl's output filename from CSV metadata
  (`_predict_output_filename` / `sanitize_filename`, which must exactly mirror
  spotdl's own sanitization) and checks it against a library index before
  downloading, to skip tracks already on disk.
- `--validate-only` — reports existing/new without downloading.
- `_check_existing()` — orchestrates the above against `organize.library`'s
  index-building functions (cross-package dependency).
- `_resolve_output_dir()` — duplicated verbatim in `yt_dlp_downloader.py`.
- FFmpeg path resolution (`FFMPEG_PATH` / `ffmpeg_path` dual-case env) is
  copy-pasted here and elsewhere.

### `yt_dlp_downloader.py` (cli: `ytdl`)
Downloads a single track, set/playlist, or album from any yt-dlp-supported URL
(SoundCloud, YouTube, etc.) via yt-dlp.
- `download_ytdl()` — single vs. playlist output templates differ (Windows'
  null-byte handling corrupts the conditional `%(playlist&...)s` template, so
  two separate templates are used instead).
- `is_playlist_url()` — regex-based playlist/set detection.
- `-m/--metadata-only` — lists tracks without downloading.
- Same `_resolve_output_dir()` duplication and FFmpeg-path duplication as
  `download_spotify.py`.

### `retry_failures.py` (cli: `retry`)
**Source lost — file only survives as a docstring + constants; the actual
logic (union reasons across `failed_downloads.txt`/`soft_failures.txt`,
hard/soft exclusion, `--report-csv` manual-hunt sheet generation) needs to be
rebuilt from the README description, not ported.** Per the README, it should:
- Compile both failure logs into `retry_list.txt`, deduping URLs and unioning
  their failure reasons.
- Exclude `track_unavailable` (hard failure) by default unless
  `--include-unavailable`.
- Re-check remaining URLs against the library (reusing
  `download_spotify`'s exact predicted-filename matching path) so the retry
  list only contains what's still actually missing.
- `--report-csv` — write a manual-hunt sheet (`artist, track, album, reason,
  spotify_url, search`) sorted by artist → album → track, with a clickable
  YouTube search link per row.

### `soundbyte_albums.py` (cli: `soundbyte`)
Pulls top-N albums from a Firebase Firestore collection (a separate personal
project, "soundbyte"), searches Spotify for each, and exports:
- `soundbyte_albums.csv` / `soundbyte_album_urls.txt` — album-level.
- With `--expand-albums`: expands each matched album into its tracks and
  writes `soundbyte_tracks.csv` in the exact same column shape as
  `spotify_manifest.csv`, so `spotify --pre-skip-existing` can use it (a plain
  album-URL list has no track metadata to predict filenames from).
- `_get_spotify_token()` — a **second, independently hand-rolled** Spotify
  client-credentials auth flow using raw `requests` calls, not
  `spotify_utils`/spotipy. Legitimate to be a separate auth flow
  (client-credentials needs no user login) but shouldn't be a duplicate
  implementation.
- `search_spotify_album()` — progressively loosened search queries (exact →
  loose artist → freeform) with exact-title preference, first-result fallback.

---

## organize/

Takes raw downloads and turns them into a clean, beets-managed crate: proper
album folders, singleton handling, and artist-string normalization.

### `library.py`
Shared library-index and root-resolution helpers — imported directly by
`download/` (a cross-package dependency, since this technically lives under
`organize/`).
- `resolve_library_root()` — `ARCHIVE_PATH`/`archive_path` env, dual-cased,
  with a `~/music/tapebuilding` fallback.
- `resolve_tapedeck_root()` — same pattern for `TAPEDECK_PATH`.
- `_normalize()` — lowercase, strip non-alphanumeric, collapse whitespace.
  **Functionally identical** to `organize.cleanup.norm_key` — independently
  defined.
- `build_library_index()` — glob-scans the library root for audio files,
  indexes normalized filename stems into a set.
- `scan_existing()` / `scan_existing_fuzzy()` — check candidate filenames
  against the index; fuzzy version normalizes both sides first.

### `cleanup.py`
Two jobs live in one file: (1) a **toolkit** of tag-reading/normalizing/moving
primitives reused by `preimport.py`, `playlists/matcher.py`, and
`tapedeck/resolve.py`; (2) the **regroup-in-place** policy that fixes an
already-imported crate.
- Toolkit: `EXTENSIONS`, `norm_key()`, `sanitize()`, `primary_token()`,
  `read_tags()`, `canonical_albumartist()`, `dominant_album()`,
  `scan_audio()`, `safe_move()`, `write_albumartist()`, `resolve_crate()`.
- Also defines a **second, dead-duplicate** normalize function `norm()` at the
  bottom of the file, used only by `write_albumartist()` — functionally
  identical to `norm_key()`.
- Policy: repairs two beets import failure modes — (a) albums split into
  per-track-artist folders because incoming files had no `albumartist` tag,
  so beets keyed the path template on the varying track artist; (b) whole
  albums scattered as loose singletons because the singles pass has no album
  grouping. Regroups by album tag straight off file tags (independent of
  beets/beets.db), computes a canonical albumartist per group (dominant
  artist string → dominant primary collaborator → `Various Artists`), moves
  files into `albums/<AlbumArtist> - <Album>/` or `singles/<Artist> -
  <Title>`, and writes the canonical albumartist tag so a future re-import
  won't re-split the group. Idempotent.
- `--rebuild-db` — deletes and rebuilds `beets.db` via an as-is (no
  MusicBrainz) reimport matching the reorganized crate.
- Flags plausible wrong-merges (unusually large album groups) and VA-filed
  albums in its dry-run summary for manual review.

### `preimport.py`
Runs the same regrouping logic **before** beets ever sees the drop, so the
importer doesn't need to be fixed up after the fact. Built almost entirely
from `cleanup.py`'s toolkit functions.
- `stage()` — main entry, called automatically by `beets_import.py` unless
  `--no-preimport`.
- Three outcomes per album-tag group: **merge** into an existing crate album
  folder (matched by normalized albumartist+album against
  `index_existing_albums()`), **stage** a new folder under
  `<input>/albums/` (≥2 tracks, no existing match), or **pass** (lone track,
  left for the beets singles pass).
- `index_existing_albums()` — maps existing crate albums by
  `(norm(albumartist), norm(album))`; a collision across ≥2 existing folders
  marks the key ambiguous (`None`) so a merge is refused rather than risking
  binding two different real albums that share a normalized name — staged as
  a new folder instead.
- Merge-target duplicate detection (`_existing_titles()`) — skips
  incoming tracks the target album folder already owns (e.g. an mp3
  straggler of a track present as flac), quarantining them to
  `<crate>/duplicates/` instead of creating a same-album intra-folder
  duplicate that beets' `duplicate_action: skip` wouldn't otherwise catch.
- Returns a `report` dict (`staged_folders`, `merged_folders`,
  `merged_tracks`, `duplicates`, `ambiguous`, `singletons`, `tag_writes`)
  that `beets_import.py` consumes to warn that merged tracks are on disk but
  not yet in `beets.db`.

### `beets_import.py` (cli: `import`)
Two-pass beets importer: pass 1 groups multi-track albums and matches
against MusicBrainz; pass 2 imports remaining loose tracks as singletons.
- `run_album_pass()` / `run_singles_pass()` — shell out to `beet import`
  with `--pretend` (dry-run), `--timid` (prompt on uncertain matches) or
  `--quiet` (auto-accept strong matches, skip uncertain), `--singletons`.
- `_album_pass_target()` — careful dispatch: when preimport ran, the album
  pass targets *only* `<input>/albums/` (what preimport just staged), and is
  skipped entirely if preimport staged nothing — never falls through to a
  flat directory of loose singletons, which beets would otherwise group into
  one bogus multi-track album.
- `_warn_singles_after_albums()` — warns if `albums/` still holds audio when
  running a singles-only pass (the singles pass is recursive and would import
  those album tracks as individual singletons).
- `export_library_csv()` / `print_library_stats()` — dump/summarize the
  beets library via `beet ls -f`.
- Runs `organize.preimport.stage()` automatically before both passes unless
  `--no-preimport`.

### `normalize_artists.py`
A beets plugin (not a CLI tool) — normalizes artist/albumartist strings at
import time into a consistent `"A, B & C"` form, handling `feat.`/`ft.`,
collab `x`, and `and` separators. Registered via `config.yaml`'s `plugins`
list + `pluginpath`. Self-contained, no notes.
- `normalize_artist()` — the core string transform.
- `NormalizeArtistsPlugin` — hooks `import_task_choice` (pre-path-template),
  `album_imported`/`item_imported` (post-import correction).

### `config.yaml` / `config.yaml.example`
Beets configuration. The example is a properly path-templated version of the
real (machine-specific, gitignored) config — correct pattern, not a bug.
Real config hardcodes an absolute crate path and `pluginpath`.

---

## playlists/

Builds and maintains local `.m3u8` files from Spotify playlists, resolving
each track to a file in the crate. The most mature subsystem in the repo —
tiered fuzzy matching, cached crate index, atomic file writes.

### `indexer.py`
Builds a local catalog of the crate for track matching (has to cover
`albums/`, `singles/`, **and** `soundtracks/`, which `beets.db` does not
index — hence tag-reading the filesystem directly rather than querying
beets).
- `build_index()` — recursive `mediafile` walk, skipping the `playlists/`
  subtree at the crate top level. Reuses `organize.cleanup`'s tag-reading
  idiom, but **re-implements it independently** (`_read_entry()`) rather than
  calling `cleanup.read_tags()` — duplicated field list.
- `get_index()` — returns the cached catalog, rebuilding the jsonl sidecar
  (`.playlist_index.jsonl` under the exports dir) on miss or `--reindex`.
- `save_index()` / `load_index()` — atomic jsonl write, tolerant read.
- `resolve_playlists_path()`, `resolve_archive_path()`, `resolve_exports_dir()`
  — **another** independent copy of the CLI-arg-or-dual-case-env-or-fallback
  resolution pattern seen in `organize.library`.

### `matcher.py`
Maps a Spotify track row to a local file via progressive relaxation — no
ISRC available in the exports, and the library is mostly beat
tapes/bootlegs that won't match MusicBrainz, so matching is by name.
- Six tiers, first hit wins: (1) exact title + primary-artist token, (2)
  exact title + any artist overlap, (3) exact title + exact album +
  duration, (4) core title (feat. clause stripped from the **local** tag) +
  artist overlap — rescues a local `"Title (feat. X)"` against a clean
  Spotify `"Title"`, (5) fuzzy title (≥0.92 ratio, same 4-char prefix) +
  duration, hesitant, (6) all-symbol titles (normalize to empty string,
  e.g. `"$$$"`) — exact raw title then `(album, track-number)` position,
  each guarded by artist/album/duration so a generic symbol title can't
  cross-match an unrelated track.
- `MatchIndex` — preprocesses the catalog into title/prefix/core-title/raw-
  title/album-track lookup groups once per build run.
- Imports `organize.cleanup.norm_key` directly for its base normalization,
  but layers its own `_core_title()`/`_FEAT_PAREN` feat-stripping logic on
  top rather than reusing `spotify_utils`'s equivalent — a third independent
  feat-aware normalization.
- `match_rows()` — caches results by Spotify track ID (a track in many
  playlists resolves once per run).

### `m3u.py`
Writes/reads extended `.m3u8` playlists.
- `render()` / `write_m3u8()` — atomic write (tmp + `os.replace`). Each entry
  gets a `#SPOTIFY:<track_id>` comment line (ignored by players) for a future
  reverse-sync, plus a standard `#EXTINF`. Paths are written relative to the
  `.m3u8`'s own folder so the file stays portable under a synced crate tree.
- `safe_name()` — filesystem-safe playlist filename; transliterates non-ASCII
  rather than underscoring it.
- `parse_spotify_ids()` — recovers the ordered Spotify track ID list from a
  written `.m3u8` (for the planned reverse-sync).
- **Note:** `tapedeck/resolve.py` independently parses the same file format
  for its path lines (`_parse_m3u8`) rather than extending this module —
  two readers of one file format living in two packages.

### `build.py` (cli: `playlists`)
Orchestrates export (optional rescrape) → track/playlist selection → catalog
matching → `.m3u8` writing → unmatched handoff.
- `build_playlists()` — main entry.
- `_select_playlists()` — scope resolution: `-p/--playlist` (by name or ID,
  repeatable) overrides `--all`/`--mine` (default: owned playlists only).
- `_scope_rescrape()` — when `--rescrape` is combined with `-p`, fetches and
  patches in *only* the named playlist(s)' rows rather than re-running a full
  `export_all_data()` walk of every owned playlist — a real, nontrivial
  feature (id resolution from an existing `playlists.csv`, in-place row
  replacement preserving CSV order).
  `--covers` downloads each playlist's cover art.
- `_write_unmatched()` — non-fatal, atomic write of `unmatched.csv` +
  `unmatched_urls.txt` (feeds directly back into `spotify -u`).
- Imports `download.spotify_utils` (`authenticate_spotify`,
  `get_playlist_tracks`) and `download.spotify_to_csv` (`export_all_data`,
  `extract_playlist_id_from_url`) directly — confirms `playlists` depends on
  `download`'s auth/export layer as much as it depends on `organize`'s
  index/tag layer.

---

## tapedeck/

Mirrors a rotation subset of the crate 1:1 by crate-relative path into a
sync target (`TAPEDECK_PATH`), for offline/roaming playback on another
device. No downloading, no Spotify — purely a copy/hardlink of a slice of
the crate that already exists.

### `paths.py`
Thin per-package wrapper resolving the three roots tapedeck touches (crate,
tapedeck, playlists+exports), delegating to `organize.library` and
`playlists.indexer`'s resolvers rather than reimplementing them — the
correct instinct, just currently pointed at two different sibling packages
instead of one shared one.

### `resolve.py`
Turns a `(kind, spec)` pair into crate paths to stage, where `kind` is one of
`album`/`song`/`soundtrack`/`playlist` and `spec` is either a crate-relative
path (fast, unambiguous, skips the index entirely) or a name (resolved
against the crate).
- Returns four buckets: `folders` (whole-subtree mirrors — albums,
  soundtracks), `files` (individual audio files — songs, playlist tracks),
  `m3u8` (playlist files copied verbatim), `warnings` (unresolved specs,
  ambiguity notes — never fatal). This bucket split is what lets `copy.py`
  stage/unstage generically without knowing what kind of thing it's moving.
- `need_index_for()` — decides whether the invocation needs the cached crate
  index at all; path-form specs and soundtrack/playlist kinds never do, an
  album name matching a folder basename doesn't either — only album-by-tag
  fallback and song-by-name actually need it, so the (potentially expensive)
  index build is skipped whenever possible.
- Per-kind resolvers (`_resolve_album`, `_resolve_song`, `_resolve_soundtrack`,
  `_resolve_playlist`) each degrade gracefully: path match first, then
  folder/dir basename match, then (for album/song) a tag-based fallback via
  the catalog.
- Imports `organize.cleanup.norm_key` and `playlists.matcher.MatchIndex`/
  `_split_artists` directly — confirms tapedeck depends on both the
  normalization toolkit and the playlists catalog/matcher subsystem as core
  primitives, not incidentally.
- `_parse_m3u8()` — a **second** reader of the `.m3u8` path-line format
  (`playlists/m3u.py` is the first), extracting existing/missing referenced
  files rather than track IDs.

### `copy.py`
Generic stage/unstage over the four resolved buckets — doesn't know or care
what `kind` it's handling except for one exception (playlist unload
refcounting).
- `stage()` — copies (default) or hardlinks (`--link`, same-volume only)
  every resolved file to its crate-relative mirror path under the tapedeck
  root; skips existing destinations unless `--overwrite`. Folders expand to
  their full subtree (audio + cover/`.pdf` siblings) for a complete mirror.
- `unstage()` — the inverse; removes the mirrored file for every resolved
  path, then prunes now-empty parent directories back up to (not including)
  the tapedeck root.
- **Playlist unload is refcounted**: an audio file is removed only if no
  *other* `.m3u8` still staged under `tapedeck/playlists/` references it, so
  two playlists sharing a track don't lose it when one is unloaded. This
  refcount is playlist-scope only — it doesn't know about files staged via
  `load album`/`load song`, so unloading a playlist can punch a hole in an
  independently-loaded album copy if the same track is shared. Documented as
  a known sharp edge, not silently wrong.
- Imports `tapedeck.resolve._parse_m3u8` — a private, underscore-prefixed
  cross-file import.

### `deck.py` (cli: `tapedeck`)
Subcommands: `load`, `unload`, `list`.
- `_maybe_index()` — fetches the cached crate index + matcher only when
  `need_index_for()` says the invocation actually needs it.
- `_load()` / `_unload()` — resolve → summarize → stage/unstage, all
  dry-run-by-default (matching the rest of the repo's `--apply` convention).
- `_list()` — walks the tapedeck root, summarizing file/folder counts and
  sizes per subtree (`albums`, `singles`, `soundtracks`, `playlists`), with
  `--verbose` per-folder/per-file detail.

---

## pipelines/ (being renamed to core/)

Opinionated multi-step workflows stitching the single-purpose CLIs together.
Currently implemented as **subprocess orchestration** (`python -m
download.download_spotify`, etc.) rather than in-process function calls —
this is the one architectural choice being deliberately changed in the
refactor (see `REFACTOR_PLAN.md`).

### `download_songs.py`
Runs download → beets-import → playlists-reindex end to end.
- `_resolve_source()` — accepts an existing file/dir, or a bare Spotify URL
  (written to a temp one-line `.txt` for the child CLI to consume).
- `_run()` — prints + runs a child CLI; dry-run by default (prints the exact
  child command, runs nothing — even skips the playlists index sidecar
  rebuild a real `--reindex` run would otherwise touch). `--apply` runs for
  real; `--only` (repeatable) restricts to a subset of the three steps,
  always executed in fixed order regardless of `--only`'s given order.
- Each step keeps its own argparse/`.env`/encoding handling by virtue of
  being a genuinely separate subprocess — the tradeoff being no structured
  return value, only a shell exit code.

The README also documents a second, un-wrappered "pipeline" — `playlists
--apply --rescrape` — as the full export+build+handoff sync flow, needing no
dedicated wrapper because `playlists.build` already does all three steps
itself.

---

## tapebuilding/ (legacy, being deleted)

An earlier, parallel implementation (`downloader.py`, `exporter.py`,
`importer.py`, `pipeline.py`, `retry.py`, plus a `core/` subpackage with
`config.py`/`logger.py`/`utils.py`) of functionality that now lives properly
in `download/`, `organize/`, and `pipelines/`. Not inventoried in detail —
confirmed dead weight, scheduled for deletion rather than migration.

---

## Cross-cutting issues found across every package

These are the concrete findings that motivate `REFACTOR_PLAN.md`'s `lib/`
design — repeated here in one place for reference.

1. **Four independent normalization functions** doing near-identical work:
   `organize.library._normalize`, `organize.cleanup.norm_key` (plus its own
   dead-duplicate `norm()`), `download.spotify_utils._normalize_title`, and
   `playlists.matcher`'s `_core_title`/`_FEAT_PAREN` logic. Two real tiers
   hide inside these four: a bare normalize (lowercase, strip non-
   alphanumeric, collapse whitespace) and a title-aware normalize (also
   strips `feat.`/parenthetical clauses).
2. **Four independent copies of root-resolution logic**, all doing
   `cli_arg or os.getenv('X_PATH') or os.getenv('x_path') or fallback`:
   `organize.library` (crate, tapedeck), `playlists.indexer` (playlists,
   exports), `tapedeck.paths` (wraps the above two), plus inline
   `os.getenv('ARCHIVE_PATH') or os.getenv('archive_path')` in
   `beets_import.py` and `download_songs.py`.
3. **Duplicated tag-reading**: `organize.cleanup.read_tags()` and
   `playlists.indexer._read_entry()` both open files with `MediaFile()` and
   extract overlapping field sets, independently.
4. **Duplicated m3u8-format readers**: `playlists.m3u.parse_spotify_ids()`
   and `tapedeck.resolve._parse_m3u8()` both parse the same file format for
   different fields (track IDs vs. path lines), in two different packages.
5. **Two independent Spotify auth flows** that should be one module with two
   sanctioned functions: `spotify_utils.authenticate_spotify()` (user OAuth)
   and `soundbyte_albums._get_spotify_token()` (hand-rolled client-
   credentials via raw `requests`).
6. **Cross-package imports that reveal the real dependency graph**:
   `download → organize.library`, `playlists → download.spotify_utils` +
   `download.spotify_to_csv`, `playlists → organize.cleanup`,
   `tapedeck → organize.library` + `organize.cleanup` + `playlists.indexer`
   + `playlists.matcher`. Every domain package already depends on at least
   one sibling for a "shared" concern — none of them are actually
   independent today, despite that being the original design intent.
7. **Copy-pasted helpers within a single package**: `_resolve_output_dir()`
   duplicated verbatim between `download_spotify.py` and
   `yt_dlp_downloader.py`; FFmpeg-path env resolution duplicated in both.
8. **`retry_failures.py`'s real logic is lost** — only the docstring and
   constants survive; must be rebuilt from the README description.
9. **`.env` dual-casing** (`ARCHIVE_PATH` vs. `archive_path`, etc.) is a
   documented "convention," not an accident — but it means every root
   resolver has to remember to check both cases, which is exactly the kind
   of repeated boilerplate a single shared resolver should absorb once,
   rather than every call site re-implementing the fallback chain.
