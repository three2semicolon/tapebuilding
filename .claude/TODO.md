# tapebuilding — refactor todo

Companion to `PACKAGE_OVERVIEW.md` (current state) and `REFACTOR_PLAN.md`
(target state and rationale). Work top to bottom — later phases depend on
earlier ones being done, since `lib/` is what everything else gets rebuilt
against.

Check items off as they're completed. Leave a short note under any item that
ends up deviating from the plan (renamed something differently, merged two
planned files, decided against dropping dual-case env vars, etc.) so the
docs can be updated to match reality afterward instead of drifting from it.

---

## Phase 0 — housekeeping

- [X] Delete `tapebuilding/` package entirely (legacy, superseded by
  `download/`, `organize/`, `pipelines/`).
- [X] Remove all existing `README.md` files from every package (per-package
  docs will be rewritten once the refactor settles; stale docs mid-
  refactor are worse than no docs).
- [X] Remove all existing `__init__.py` files from every package (will be
  recreated as needed once module contents stabilize).
- [X] Rename `pipelines/` → `core/` (directory rename only at this point;
  contents still reference the old subprocess-based approach until
  Phase 6).
- [X] Decide and record: keep the dual-case env var fallback, or drop it in
  favor of upper-case-only? (Plan recommends dropping it.) Update
  `.env.example` to match whatever's decided.
  - Decided: dropped, upper-case only. `lib/paths.py` implements this
    (`resolve()` checks only `os.getenv(env_name)`, no lower-case fallback).
    `.env.example` still needs a pass to confirm it only lists upper-case
    names — not yet done, needs the actual file.

## Phase 1 — build `lib/`

Build this fully before touching the domain packages — everything else in
this list assumes `lib/` already exists and is correct.

- [X] `lib/paths.py`
  - [X] `resolve(env_name, cli=None, default=None, required=False)` — the
    one general-purpose resolver.
  - [X] `archive_path(cli=None)`
  - [X] `tapedeck_path(cli=None)`
  - [X] `playlists_path(cli=None)` (required, no fallback — matches current
    `resolve_playlists_path` behavior of raising if unset)
  - [X] `exports_dir(playlists_path=None, cli=None)`
- [X] `lib/text.py`
  - [X] `normalize_key(s)` — consolidate `organize.library._normalize`,
    `organize.cleanup.norm_key`, `organize.cleanup.norm` (delete the
    dead-duplicate entirely, don't port it).
  - [X] `normalize_title(s)` — consolidate `spotify_utils._normalize_title`
    and `matcher.py`'s `_core_title`/`_FEAT_PAREN` feat-stripping logic.
  - [X] `primary_artist(s)` — from `spotify_utils._fuzzy_key`'s primary-split
    and `matcher.py`'s `_primary_artist`.
  - [X] `split_artists(s)` — from `matcher.py`'s `_split_artists`.
  - [X] Write a few inline sanity checks (feat. stripping, collab `x`/`and`
    handling, symbol-only titles) since this function gets used
    everywhere downstream — a regression here is a silent, wide-blast-
    radius bug.
    - Note: confirmed `split_artists()` does *not* treat plain `" and "` as
      a separator (only comma/&//  x / vs / feat-family, matching
      `playlists/matcher.py`'s original `_split_artists` exactly). That's
      different from `organize/normalize_artists.py`'s beets plugin, which
      does handle `and` — that's a separate, deliberately untouched
      subsystem, not a `lib.text` gap. Added an assertion pinning this down
      so it doesn't get "fixed" into an inconsistency later.
- [X] `lib/tags.py`
  - [X] `EXTENSIONS` constant.
  - [X] `sanitize(s)` — from `organize.cleanup.sanitize`.
  - [X] `read_tags(path)` — merge `organize.cleanup.read_tags` (tuple return)
    and `playlists.indexer._read_entry` (dict return, adds `length`,
    `path`) into one dict-returning function every caller can use.
  - [X] `write_tag(path, **fields)` — generalize
    `organize.cleanup.write_albumartist` to arbitrary tag fields.
  - [X] `canonical_albumartist(files)`, `dominant_album(files)`,
    `scan_audio(root, subdirs=None)`, `safe_move(src, dst)` — ported
    directly from `organize.cleanup`.
  - [X] `primary_token(raw)` if still needed after `lib.text` lands, or fold
    it into `lib.text.primary_artist`.
    - Note: kept as its own function in `lib.tags` (narrower than
      `lib.text.primary_artist` — only splits on `&`/`/`, used specifically
      by `canonical_albumartist()`), not folded in.
- [X] `lib/m3u.py`
  - [X] `write_m3u8(path, entries)`, `safe_name(name)` — ported from
    `playlists/m3u.py`.
  - [X] `read_m3u8(path)` — merge `playlists.m3u.parse_spotify_ids` (track
    IDs) and `tapedeck.resolve._parse_m3u8` (existing/missing path
    lines) into one reader returning both.
- [X] `lib/spotify_auth.py`
  - [X] `authenticate_user()` — ported from `spotify_utils.authenticate_spotify`.
    Fix the token cache path to be anchored (config dir or similar), not
    a bare relative `token_cache`.
  - [X] `authenticate_client()` — rewrite `soundbyte_albums._get_spotify_token`
    on spotipy's client-credentials flow instead of raw `requests` calls.
- [X] `lib/catalog/indexer.py`
  - [X] Port `playlists/indexer.py` wholesale; swap its own tag-reading for
    `lib.tags.read_tags()`; swap its root resolvers for `lib.paths`.
- [X] `lib/catalog/matcher.py`
  - [X] Port `playlists/matcher.py` wholesale; swap its normalization calls
    for `lib.text.normalize_key`/`normalize_title`/`primary_artist`/
    `split_artists`. Preserve all six matching tiers exactly — this is
    one of the two "don't simplify, just relocate" subsystems in the
    repo.
    - Note: the original `matcher.py` source wasn't available to port
      character-for-character — rebuilt from `PACKAGE_OVERVIEW.md`'s tier
      descriptions instead, then verified against the real
      `spotify_manifest.csv` row shape (`track_name`/`artist_names`/
      `album_name`/`duration_ms`) once `spotify_utils.py` was in hand.
      Worth a side-by-side diff against the pre-refactor file if it's still
      recoverable anywhere, just to confirm no tier's edge-case behavior
      drifted during the rebuild.
- [X] Sanity pass: grep the new `lib/` tree for any remaining reference to
  `organize.`, `download.`, `playlists.`, or `tapedeck.` — `lib/` must
  not depend on any domain package, only the reverse.

## Phase 2 — `organize/`

- [X] Strip the toolkit half out of `cleanup.py`, leaving only the
  regroup-in-place policy (`group_files`, `build_plan`,
  `prune_empty_dirs`, `rebuild_db`) plus its own `cli.py`-bound `main`.
- [X] Update `cleanup.py` to import the toolkit functions from `lib.tags`
  and `lib.text` instead of defining them locally.
- [X] Update `preimport.py`'s imports the same way (it already imports most
  of its primitives from `cleanup.py` — repoint those imports at `lib.tags`
  and `lib.text` directly instead of via `cleanup.py`).
  - Only `group_files`/`resolve_crate` still come from `organize.cleanup`,
    deliberately — organize-specific policy, not a generic `lib/` concern.
- [X] Extract `cli.py` from both `cleanup.py` and `preimport.py`'s existing
  `main()` functions; confirm `beets_import.py`'s call into
  `organize.preimport.stage()` still works unchanged (it calls the
  function directly, not through `preimport`'s CLI, so this should be a
  no-op if the function signature doesn't change).
  - Confirmed no-op: `beets_import.run_import()` still calls
    `organize.preimport.stage(input_dir, output_dir, apply=..., merge_existing=...,
    verbose=...)` directly, matching `stage()`'s signature.
  - Fixed on review: `import_cmd` was calling a local `archive_path_default()`
    wrapper that just re-imported and called `lib.paths.archive_path()`,
    shadowing the already-imported top-level `archive_path` — leftover
    from the extraction. Now calls `archive_path()` directly. Also dropped
    a stray duplicate `import os` near the bottom of the file (`os` is
    already imported at the top).
- [X] `beets_import.py`: extract `cli.py`; replace the inline
  `os.getenv('ARCHIVE_PATH') or os.getenv('archive_path')` with
  `lib.paths.archive_path()`.
- [X] `normalize_artists.py`: leave untouched (beets plugin, not a CLI tool,
  no dependency on anything being refactored).
- [X] Confirm `config.yaml.example` still matches reality; leave the real
  `config.yaml` as machine-specific/gitignored.
  - Checked against the real `config.yaml`: matches on every setting
    (`import`, `match`, `plugins`, `fetchart`, `embedart`, `ui`). Only
    differences are the expected ones — placeholder path vs.
    `Y:/music/crate/...`, and the example's repo-relative `pluginpath`
    vs. the real absolute one.
- [ ] Delete `library.py` once nothing imports it anymore (its contents now
  live in `lib.paths`/`lib.tags`/`lib.text`) — double check `download/`
  and `tapedeck/` (pre-refactor) don't have a stray leftover import.
  - `download/` is clear (Phase 3 already repointed `spotify_download.py`
    off `organize.library`). **Not yet safe to delete**: `tapedeck/paths.py`
    still delegates to `organize.library`'s resolvers per
    `PACKAGE_OVERVIEW.md`, and Phase 5 (which repoints `tapedeck/` at
    `lib.paths` directly) hasn't started. Revisit once Phase 5's `paths.py`
    item is done.

## Phase 3 — `download/`

- [X] `spotify_export.py` (was `spotify_to_csv.py`): extract `cli.py`;
  no other changes expected (`extract_playlist_id_from_url` stays here
  since it's Spotify-export-specific, not a generic `lib/` concern).
  - `export_main()` now lives in `download/cli.py`.
- [X] `spotify_utils.py` → fold into the package: keep
  `get_user_playlists`/`get_playlist_tracks`/`get_liked_songs`/
  `merge_and_deduplicate`/`export_to_csv`/`export_manifest_as_txt`/
  `get_export_dir` here (rename file if it makes sense once `cli.py`
  split settles); replace `authenticate_spotify()` calls with
  `lib.spotify_auth.authenticate_user()`; replace `_normalize_title`/
  `_fuzzy_key` with `lib.text.normalize_title`/`primary_artist`.
  - Renamed to `spotify_api.py` (per the file's own "rename if it makes
    sense" note — everything left after auth/normalize moved out is
    strictly "talk to the spotify web api + write csvs").
  - `get_export_dir()` kept as a function (not deleted) but is now a
    one-line wrapper over `lib.paths.exports_dir()` — its old default
    (`<repo>/export`, a sibling of the `download/` package) is gone;
    spotify csvs now live under `PLAYLISTS_PATH/exports` like the plan
    says, alongside the catalog sidecar. Kept the wrapper (instead of
    having every call site import `lib.paths.exports_dir` directly) so
    `spotify_export.py`/`cli.py` didn't need their import lines touched
    beyond the module rename.
  - Extracted `_extract_track()` inside `spotify_api.py` — the playlist-
    track and liked-songs fetchers were duplicating the same ~20-line
    per-item parse; this is new-during-migration, not called out in the
    plan, flagging in case it wasn't wanted.
- [X] `spotify_download.py` (was `download_spotify.py`): extract `cli.py`;
  replace `_resolve_output_dir()` — deduplicate this one function
  instead of leaving it copy-pasted (put it here since ytdl needs the
  identical helper — consider whether it's generic enough for `lib.paths`
  or genuinely download-package-local); replace the `organize.library`
  imports (`resolve_library_root`, `build_library_index`,
  `scan_existing_fuzzy`, `_normalize`) with `lib.paths`/`lib.tags`/
  `lib.text` equivalents; replace the FFmpeg-path-resolution duplication
  with a single shared helper (in this package, or `lib.paths` if ytdl
  needs it too — it does).
  - `resolve_library_root()` → `lib.paths.archive_path()`. FFmpeg
    resolution → `lib.paths.ffmpeg_path()` (already existed, no new
    helper needed there).
  - `build_library_index()`/`scan_existing_fuzzy()` are **not** a
    `lib.tags`/`lib.catalog` concern — they're a fast, filename-only
    existence check (no tag reads), deliberately cheaper than
    `lib.catalog`'s full tag-based index, used only to skip
    already-downloaded tracks before a run. Landed in a new
    `download/existing.py` instead — not in the original module list,
    but `_resolve_output_dir()`'s note ("ytdl needs the identical
    helper... consider whether it's lib-worthy") applies here too, so
    this is set up for `ytdl.py` to import from directly once it's
    migrated, same as planned for `_resolve_output_dir`.
  - `_resolve_output_dir()` itself is still local to `spotify_download.py`
    for now (unchanged from the original) — genuinely duplicating it into
    `ytdl.py` is still pending that file's migration; **do not** copy it a
    second time when `ytdl.py` lands, move it to `download/existing.py` (or
    a new small shared module) alongside the index helpers instead.
  - `organize.library._normalize` → `lib.text.normalize_key`.
- [X] `ytdl.py` (was `yt_dlp_downloader.py`): extract `cli.py`; use the same
  shared `_resolve_output_dir`/FFmpeg-path helper as `spotify_download.py`
  instead of a second copy; replace its `organize.library` import
  similarly.
  - Landed in `download/existing.py` as `resolve_output_dir()` (no leading
    underscore — it's a genuine two-caller shared helper now, not a private
    implementation detail of one file) alongside the filename-index helpers
    noted above, per that module's own forward-note.
  - FFmpeg resolution imported as `from lib.paths import ffmpeg_path as
    resolve_ffmpeg_path` — `download_ytdl()`'s own `ffmpeg_path` parameter
    (the CLI's `--ffmpeg` override) would otherwise shadow the import.
- [X] `retry.py` (was `retry_failures.py`): rebuilt from the README
  description, not ported — the real logic was lost. Implemented per the
  README:
  - [X] Read + union `failed_downloads.txt` and `soft_failures.txt`,
    deduping URLs, unioning failure reasons per URL.
  - [X] Exclude `track_unavailable` (hard failure) by default; keep with
    `--include-unavailable`.
  - [X] `--no-check` — skip the library re-check, just combine + dedupe.
  - [X] Default: re-check remaining URLs against the library using the same
    exact-match path `spotify_download.py --pre-skip-existing` uses
    (predict filename from CSV metadata → normalize → check against
    `download.existing`'s library index), so `retry_list.txt` is
    consistent with what a real download run would itself skip.
  - [X] `--metadata`/`--library` overrides.
    - Renamed to `--metadata-source`/`--library-root` in `cli.py` for
      clarity against the other commands' `--output`.
  - [X] `--report-csv` — write the manual-hunt sheet (`artist, track, album,
    reason, spotify_url, search`), sorted by artist → album → track, with
    a clickable YouTube search-results link per row.
  - [X] `-o/--output`; grouped breakdown (already on disk, no metadata,
    hard-excluded, retry list).
    - `-v/--verbose` dropped — `run_retry()` always returns the full
      breakdown dict and `cli.py` always prints the summary from it, so
      there's no non-verbose mode to opt out of.
    - `DEFAULT_REPORT` constant exists in `retry.py` but is currently
      unused — `cli.py`'s `--report-csv` requires an explicit path rather
      than defaulting to it. Minor inconsistency, easy to wire up later if
      a bare `--report-csv` flag (no path) is wanted.
  - [X] Written against `lib.paths`/`lib.text`/`download.existing` from the
    start — no old cross-package imports to clean up, since it's new code.
- [X] `soundbyte.py` (was `soundbyte_albums.py`): extract `cli.py`; replace
  `_get_spotify_token()` with `lib.spotify_auth.authenticate_client()`.
  - Added `run_soundbyte()` as a single orchestrating entry point (fetch →
    enrich → album export → track expand → track export), so `cli.py` has
    one function to call instead of five, matching `retry.run_retry()`'s
    shape. Not in the original module list — flagging since it's new
    structure, not a straight port.
- [X] `cli.py`: rewritten from argparse to a `click.group()` named
  `download`, with one subcommand per operation (`export`, `spotify`,
  `ytdl`, `retry`, `soundbyte`) instead of the old separate
  `export_main`/`spotify_main` entry points. Pyproject should point a
  single `download = "download.cli:download"` entry point at it (was two
  separate `module:main` lines).
- [X] Delete `spotify_to_csv.py` (the pre-refactor top-level script, not
  `download.spotify_export`) — fully superseded, and its
  `from download.spotify_utils import ...` no longer resolves now that
  Phase 3's `spotify_api.py`/`spotify_auth.py` split has landed. Confirmed
  dead, not yet actually deleted from disk.

## Phase 4 — `playlists/`

- [ ] Delete `playlists/indexer.py` and `playlists/matcher.py` — now live in
  `lib/catalog/`.
- [ ] Delete `playlists/m3u.py` — now lives in `lib/m3u.py`.
- [ ] `build.py`: extract `cli.py`; repoint all `playlists.indexer`/
  `playlists.matcher`/`playlists.m3u` imports at `lib.catalog.indexer`/
  `lib.catalog.matcher`/`lib.m3u`; confirm `_scope_rescrape()` and
  `_select_playlists()` still work unchanged (they don't touch anything
  being relocated). Its `download.spotify_utils`/`download.spotify_to_csv`
  imports stay as genuine cross-package dependencies (playlists really
  does need download's auth + export functions) — not something to
  eliminate, just confirm they still resolve correctly after download's
  own Phase 3 changes.

## Phase 5 — `tapedeck/`

- [ ] `paths.py`: likely deletable entirely — replace call sites with direct
  `lib.paths` calls, since the per-package wrapper was only there to
  paper over resolvers living in two different sibling packages, which
  no longer applies once both live in `lib/`.
- [ ] `resolve.py`: extract `cli.py`-bound pieces if any remain (most of this
  file is pure resolution logic, not CLI); repoint `organize.cleanup`
  (`norm_key`) and `playlists.matcher` (`MatchIndex`, `_split_artists`)
  imports at `lib.text` and `lib.catalog.matcher`; repoint
  `playlists.indexer.get_index` (called from `deck.py`, not `resolve.py`
  itself — check both files) at `lib.catalog.indexer`.
- [ ] `copy.py`: repoint its `tapedeck.resolve._parse_m3u8` import at
  `lib.m3u.read_m3u8()` instead (this also resolves the private-function
  cross-file import noted in the inventory).
- [ ] `deck.py`: extract `cli.py` (subcommand dispatch for
  `load`/`unload`/`list` moves here if not already isolated); repoint its
  `playlists.indexer`/`playlists.matcher` imports at `lib.catalog`.
- [ ] Confirm `tapedeck` no longer imports anything from `playlists/` at all
  once this phase is done (per the refactor plan, its only remaining
  sibling dependency should be none — everything it needed was actually
  a `lib/` concern).

## Phase 6 — `core/` (renamed from `pipelines/`)

- [ ] `download_songs.py`: replace every `subprocess.run([sys.executable, '-m', ...])` call with a direct import + function call into the
  now-refactored `download.spotify_download`, `organize.beets_import`,
  `playlists.build` functions. Preserve the existing `--only`/`--apply`/
  dry-run behavior and step ordering exactly — this is a mechanism
  change, not a behavior change.
  - [ ] Decide what a "dry run" means now that there's no child command to
    just print — likely: call each function with its own dry-run
    parameter (most already have one, e.g. `beets_import`'s `--dry-run`
    maps to a function argument) rather than skipping the call
    entirely.
  - [ ] Capture and return structured results per step (counts, success/fail)
    instead of relying on a subprocess exit code, per the refactor plan.
- [ ] `sync.py` (new): promote the README-documented `playlists --apply --rescrape` "sync" flow into an actual function here, calling
  `playlists.build`'s function directly, for symmetry with
  `download_songs.py` and so it's available to `app/` later without
  shelling out to the `playlists` CLI.
- [ ] `cli.py` (new): thin subcommand wrapper exposing `download_songs` and
  `sync` (and future presets) as CLI entry points, replacing the old
  single-script `pipelines/download_songs.py` invocation.
- [ ] Update `pyproject.toml`'s `[project.scripts]` entries to point at the
  new `core.cli` / each domain package's `cli.py`, replacing every
  scattered `module:main` reference with the new consistent pattern.

## Phase 7 — cleanup pass

- [ ] Full-repo grep for `os.getenv('ARCHIVE_PATH')`,
  `os.getenv('archive_path')`, `os.getenv('PLAYLISTS_PATH')`, etc.
  outside of `lib/paths.py` — anything left is a missed migration.
- [ ] Full-repo grep for any remaining `norm_key`/`_normalize`/
  `_normalize_title`/`_core_title`/`_FEAT_PAREN` definitions outside
  `lib/text.py` — same check for normalization.
- [ ] Full-repo grep for direct imports across domain packages
  (`from organize import`, `from playlists import`, `from download import`, `from tapedeck import`) — confirm the only remaining
  cross-package import is `playlists → download` (spotify auth/export),
  which is expected and fine; everything else should now route through
  `lib/`.
- [ ] Update `pyproject.toml` `dependencies`/`packages` list for the new
  `lib/` and `core/` package names.
- [ ] Rewrite one top-level `README.md` (and optionally per-package ones)
  reflecting the new structure — deferred deliberately until the
  structure stops moving.
- [ ] Re-add `__init__.py` files where actually needed (likely: every
  package directory, for the `pyproject.toml` package discovery to
  work) — now that contents are stable instead of guessing ahead of
  time.

## Ideas / not yet scheduled

Not part of the refactor proper — feature ideas raised while `download/`
was being finished. Recorded here so they don't get lost; slot into a real
phase (probably an addendum to Phase 3, plus a new Phase for the
SoundCloud side) once prioritized.

- [X] `download export` / `download spotify`: support a **list** of specific
  playlists (not just one), so a subset of playlists can be kept in sync
  independently of the full liked-songs + all-playlists export.
  - `--playlist`/`-p` is now multi-value (repeatable); added
    `--playlists-file` (newline-delimited, `#`-comments ignored) for a
    longer/saved list. Both combine and are deduped before fetching.
  - New `spotify_export.export_playlists()`: exports each playlist (still
    via `export_specific_playlist()`), then merges all tracks through
    `merge_and_deduplicate()` (liked-songs side passed as `[]`) into a
    scoped `playlists_manifest.csv` + `playlists_manifest_urls.txt` —
    distinct filenames from the full-library export so the two don't
    clobber each other in the same exports dir. Point
    `download spotify --pre-skip-existing -u playlists_manifest.csv` at it
    to "update" just that playlist set.
  - `spotify_api.export_manifest_as_txt()` gained an optional `filename=`
    param (defaults to the old hardcoded `spotify_manifest_urls.txt`) to
    make the second output filename possible without duplicating the
    function.
  - A single `--playlist` still goes straight through
    `export_specific_playlist()` unchanged (no merge step, same output
    filenames as before) — the merge path only kicks in for 2+ identifiers.
- [X] `download/manifest.py` (new): consolidates the csv-metadata-reading +
  filename-prediction helpers that `spotify_download.py` and `retry.py`
  had each independently written (delimiter-sniffing, requiring
  `track_name`/`artist_names` columns, first-seen-wins across multiple
  files). Both modules now import `predict_output_filename`/
  `read_csv_metadata` from here instead. `read_csv_metadata()` always
  returns a dict now (never `None`) — callers that used to check
  `is None` just check truthiness instead; behavior is identical since an
  empty dict was already the "nothing found" case in the directory
  branch.
  - `retry.py`'s import of `spotify_download._predict_output_filename`
    (the private-name cross-file import flagged earlier) is gone — both
    now import the public version from `manifest.py`.
- [ ] SoundCloud export/download, likely `download/soundcloud_export.py` +
  a `soundcloud` subcommand, mirroring the spotify export/download split.
  Moderate effort, different shape than Spotify's:
  - No separate auth/export step needed the way Spotify has a real web
    API — `yt-dlp`'s `extract_flat` (already used by `ytdl.py`'s
    `--metadata-only` path) can list a SoundCloud set/playlist's tracks
    (title, uploader, url) without downloading.
  - `download.ytdl.is_playlist_url()`/`download_ytdl()` already handle
    SoundCloud playlist download mechanics (the `/sets/` regex, playlist
    output template) — the missing piece is manifest/tracking
    infrastructure equivalent to `spotify_manifest.csv`, not download
    capability itself.
  - `download.existing`'s filename-stem index is already extension/source
    agnostic, so `--pre-skip-existing`-style "only fetch what's new"
    behavior should carry over with little change once there's a
    SoundCloud-side manifest to predict filenames from.
  - Open question: whether this warrants its own top-level package
    (`soundcloud/`) or stays inside `download/` alongside the Spotify
    modules — leaning `download/` for now, revisit if it grows its own
    matching/dedup logic the way Spotify's did.

## Phase 8 — `app/` (not started; listed for visibility only)

- [ ] Not part of this refactor. Revisit once Phases 0–7 are complete and
  settled. See `REFACTOR_PLAN.md`'s `app/` section for the constraints
  already agreed on (no subprocess/CLI dependency from below; progress
  reporting mechanism still an open question).
