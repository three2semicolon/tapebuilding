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
- [ ] Decide and record: keep the dual-case env var fallback, or drop it in
  favor of upper-case-only? (Plan recommends dropping it.) Update
  `.env.example` to match whatever's decided.

## Phase 1 — build `lib/`

Build this fully before touching the domain packages — everything else in
this list assumes `lib/` already exists and is correct.

- [ ] `lib/paths.py`
  - [ ] `resolve(env_name, cli=None, default=None, required=False)` — the
    one general-purpose resolver.
  - [ ] `archive_path(cli=None)`
  - [ ] `tapedeck_path(cli=None)`
  - [ ] `playlists_path(cli=None)` (required, no fallback — matches current
    `resolve_playlists_path` behavior of raising if unset)
  - [ ] `exports_dir(playlists_path=None, cli=None)`
- [ ] `lib/text.py`
  - [ ] `normalize_key(s)` — consolidate `organize.library._normalize`,
    `organize.cleanup.norm_key`, `organize.cleanup.norm` (delete the
    dead-duplicate entirely, don't port it).
  - [ ] `normalize_title(s)` — consolidate `spotify_utils._normalize_title`
    and `matcher.py`'s `_core_title`/`_FEAT_PAREN` feat-stripping logic.
  - [ ] `primary_artist(s)` — from `spotify_utils._fuzzy_key`'s primary-split
    and `matcher.py`'s `_primary_artist`.
  - [ ] `split_artists(s)` — from `matcher.py`'s `_split_artists`.
  - [ ] Write a few inline sanity checks (feat. stripping, collab `x`/`and`
    handling, symbol-only titles) since this function gets used
    everywhere downstream — a regression here is a silent, wide-blast-
    radius bug.
- [ ] `lib/tags.py`
  - [ ] `EXTENSIONS` constant.
  - [ ] `sanitize(s)` — from `organize.cleanup.sanitize`.
  - [ ] `read_tags(path)` — merge `organize.cleanup.read_tags` (tuple return)
    and `playlists.indexer._read_entry` (dict return, adds `length`,
    `path`) into one dict-returning function every caller can use.
  - [ ] `write_tag(path, **fields)` — generalize
    `organize.cleanup.write_albumartist` to arbitrary tag fields.
  - [ ] `canonical_albumartist(files)`, `dominant_album(files)`,
    `scan_audio(root, subdirs=None)`, `safe_move(src, dst)` — ported
    directly from `organize.cleanup`.
  - [ ] `primary_token(raw)` if still needed after `lib.text` lands, or fold
    it into `lib.text.primary_artist`.
- [ ] `lib/m3u.py`
  - [ ] `write_m3u8(path, entries)`, `safe_name(name)` — ported from
    `playlists/m3u.py`.
  - [ ] `read_m3u8(path)` — merge `playlists.m3u.parse_spotify_ids` (track
    IDs) and `tapedeck.resolve._parse_m3u8` (existing/missing path
    lines) into one reader returning both.
- [ ] `lib/spotify_auth.py`
  - [ ] `authenticate_user()` — ported from `spotify_utils.authenticate_spotify`.
    Fix the token cache path to be anchored (config dir or similar), not
    a bare relative `token_cache`.
  - [ ] `authenticate_client()` — rewrite `soundbyte_albums._get_spotify_token`
    on spotipy's client-credentials flow instead of raw `requests` calls.
- [ ] `lib/catalog/indexer.py`
  - [ ] Port `playlists/indexer.py` wholesale; swap its own tag-reading for
    `lib.tags.read_tags()`; swap its root resolvers for `lib.paths`.
- [ ] `lib/catalog/matcher.py`
  - [ ] Port `playlists/matcher.py` wholesale; swap its normalization calls
    for `lib.text.normalize_key`/`normalize_title`/`primary_artist`/
    `split_artists`. Preserve all six matching tiers exactly — this is
    one of the two "don't simplify, just relocate" subsystems in the
    repo.
- [ ] Sanity pass: grep the new `lib/` tree for any remaining reference to
  `organize.`, `download.`, `playlists.`, or `tapedeck.` — `lib/` must
  not depend on any domain package, only the reverse.

## Phase 2 — `organize/`

- [ ] Strip the toolkit half out of `cleanup.py`, leaving only the
  regroup-in-place policy (`group_files`, `build_plan`,
  `prune_empty_dirs`, `rebuild_db`) plus its own `cli.py`-bound `main`.
- [ ] Update `cleanup.py` to import the toolkit functions from `lib.tags`
  and `lib.text` instead of defining them locally.
- [ ] Update `preimport.py`'s imports the same way (it already imports most
  of its primitives from `cleanup.py` — repoint those imports at `lib.tags`
  and `lib.text` directly instead of via `cleanup.py`).
- [ ] Extract `cli.py` from both `cleanup.py` and `preimport.py`'s existing
  `main()` functions; confirm `beets_import.py`'s call into
  `organize.preimport.stage()` still works unchanged (it calls the
  function directly, not through `preimport`'s CLI, so this should be a
  no-op if the function signature doesn't change).
- [ ] `beets_import.py`: extract `cli.py`; replace the inline
  `os.getenv('ARCHIVE_PATH') or os.getenv('archive_path')` with
  `lib.paths.archive_path()`.
- [ ] `normalize_artists.py`: leave untouched (beets plugin, not a CLI tool,
  no dependency on anything being refactored).
- [ ] Confirm `config.yaml.example` still matches reality; leave the real
  `config.yaml` as machine-specific/gitignored.
- [ ] Delete `library.py` once nothing imports it anymore (its contents now
  live in `lib.paths`/`lib.tags`/`lib.text`) — double check `download/`
  and `tapedeck/` (pre-refactor) don't have a stray leftover import.

## Phase 3 — `download/`

- [ ] `spotify_export.py` (was `spotify_to_csv.py`): extract `cli.py`;
  no other changes expected (`extract_playlist_id_from_url` stays here
  since it's Spotify-export-specific, not a generic `lib/` concern).
- [ ] `spotify_utils.py` → fold into the package: keep
  `get_user_playlists`/`get_playlist_tracks`/`get_liked_songs`/
  `merge_and_deduplicate`/`export_to_csv`/`export_manifest_as_txt`/
  `get_export_dir` here (rename file if it makes sense once `cli.py`
  split settles); replace `authenticate_spotify()` calls with
  `lib.spotify_auth.authenticate_user()`; replace `_normalize_title`/
  `_fuzzy_key` with `lib.text.normalize_title`/`primary_artist`.
- [ ] `spotify_download.py` (was `download_spotify.py`): extract `cli.py`;
  replace `_resolve_output_dir()` — deduplicate this one function
  instead of leaving it copy-pasted (put it here since ytdl needs the
  identical helper — consider whether it's generic enough for `lib.paths`
  or genuinely download-package-local); replace the `organize.library`
  imports (`resolve_library_root`, `build_library_index`,
  `scan_existing_fuzzy`, `_normalize`) with `lib.paths`/`lib.tags`/
  `lib.text` equivalents; replace the FFmpeg-path-resolution duplication
  with a single shared helper (in this package, or `lib.paths` if ytdl
  needs it too — it does).
- [ ] `ytdl.py` (was `yt_dlp_downloader.py`): extract `cli.py`; use the same
  shared `_resolve_output_dir`/FFmpeg-path helper as
  `spotify_download.py` instead of a second copy; replace its
  `organize.library` import similarly.
- [ ] `retry.py` (was `retry_failures.py`): **rebuild from the README
  description**, not ported — the real logic was lost. Needs, per the
  README:
  - [ ] Read + union `failed_downloads.txt` and `soft_failures.txt`,
    deduping URLs, unioning failure reasons per URL.
  - [ ] Exclude `track_unavailable` (hard failure) by default; keep with
    `--include-unavailable`.
  - [ ] `--no-check` — skip the library re-check, just combine + dedupe.
  - [ ] Default: re-check remaining URLs against the library using the same
    exact-match path `spotify_download.py --pre-skip-existing` uses
    (predict filename from CSV metadata → normalize → check against
    `lib.catalog`/library index), so `retry_list.txt` is consistent with
    what a real download run would itself skip.
  - [ ] `--metadata <export-dir-or-csv>` / `--library <music-root>`
    overrides.
  - [ ] `--report-csv` — write the manual-hunt sheet (`artist, track, album, reason, spotify_url, search`), sorted by artist → album → track,
    with a clickable YouTube search-results link per row.
  - [ ] `-o/--output`, `-v/--verbose` (grouped breakdown: already on disk,
    no metadata, hard-excluded, retry list).
  - [ ] Write against `lib.paths`/`lib.text`/`lib.catalog` from the start —
    no old cross-package imports to clean up here since it's new code.
- [ ] `soundbyte.py` (was `soundbyte_albums.py`): extract `cli.py`; replace
  `_get_spotify_token()` with `lib.spotify_auth.authenticate_client()`.

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

## Phase 8 — `app/` (not started; listed for visibility only)

- [ ] Not part of this refactor. Revisit once Phases 0–7 are complete and
  settled. See `REFACTOR_PLAN.md`'s `app/` section for the constraints
  already agreed on (no subprocess/CLI dependency from below; progress
  reporting mechanism still an open question).
