# tapebuilding — package overview

This document describes what exists today, post-refactor: every package,
every module, what each one does and how it fits together. It replaces the
pre-refactor snapshot (and `REFACTOR_PLAN.md`, now retired — its `app/`
section lives on in `WEB_APP_PLAN.md`).

The project builds and manages a personal music library: export Spotify
data, download from Spotify/SoundCloud/YouTube, organize into a
beets-managed crate, build local playlists, and mirror a rotation subset to
a synced device.

```
src/
  lib/                  shared foundation - no domain package imports this backwards
    paths.py
    text.py
    tags.py
    m3u.py
    spotify_auth.py
    catalog/
      indexer.py
      matcher.py
  download/              acquisition: spotify export/download, ytdl, retry, soundbyte
  organize/              raw downloads -> beets-managed crate
  playlists/             spotify playlist -> local .m3u8, with crate matching
  tapedeck/               mirror a rotation subset of the crate to a sync target
  core/                   opinionated multi-step workflows over the four packages above
```

Every package directory has an `__init__.py`; `pyproject.toml`'s
`[project.scripts]` points one console command per package at its
`cli.py` (`download`, `organize`, `playlists`, `tapedeck`, `core`).

---

## lib/

Shared primitives every domain package depends on. Nothing in `lib/`
imports from `download`/`organize`/`playlists`/`tapedeck` — the dependency
graph only goes one way.

### `lib/paths.py`
Single source of truth for every root path. Uppercase-only env vars — the
old dual-case (`ARCHIVE_PATH`/`archive_path`) fallback is gone.
- `resolve(env_name, cli=None, default=None, required=False)` — `cli`
  override > `os.environ[env_name]` > `default`; raises `ValueError` if
  `required` and nothing resolves. Every named resolver below is a thin
  call into this.
- `archive_path(cli=None)` — `ARCHIVE_PATH`, defaults to
  `~/music/tapebuilding` if unset. This convenience default is
  deliberately **not** used by anything that moves or renames files on
  disk (`organize.cleanup.resolve_crate()`, `organize.beets_import.run_import()`)
  — those call `resolve('ARCHIVE_PATH', required=True)` directly instead,
  so a missing `ARCHIVE_PATH` is a hard error rather than a silently
  guessed directory.
- `tapedeck_path(cli=None)` — `TAPEDECK_PATH`, defaults to
  `~/music/tapedeck`.
- `playlists_path(cli=None)` — `PLAYLISTS_PATH`, required, no fallback.
- `exports_dir(playlists_path_value=None, cli=None)` — `<playlists_path>/exports`, created if missing.
- `ffmpeg_path(cli=None)` — `FFMPEG_PATH`, no default (`None` means "let
  the tool find it on `PATH`").
- Doesn't call `load_dotenv()` itself — each package's `cli.py` does that
  once at startup.

### `lib/text.py`
Two tiers of string normalization, consolidated from four independent
pre-refactor copies.
- `normalize_key(s)` — lowercase, strip non-alphanumeric, collapse
  whitespace. The bare normalize, used for grouping/matching keys
  everywhere.
- `normalize_title(s)` — `normalize_key()`, but strips a leading
  `feat.`/`ft.`/`featuring` clause and parenthetical content first. Used
  wherever a "core" title identity matters more than the literal string.
- `primary_artist(s)` — first credited artist from an `"A, B & C"` /
  `"A feat. B"` string.
- `split_artists(s)` — all credited artists from the same kind of string,
  as a list. Deliberately does **not** treat a bare `" and "` as a
  separator (only comma/`&`/`/`/`x`/`vs`/feat-family) — that's different
  from `organize/normalize_artists.py`'s beets plugin, which does handle
  `and`, and that inconsistency is intentional (separate subsystem,
  pinned down with an assertion so it doesn't get "fixed" later).
- `strip_edition_suffix(s)` / `normalize_album(s)` — **new**: album-name
  normalization for matching/grouping (closes the `TODO.md` "album-name
  normalization / edition collapsing" item, merge-on-ingest half).
  `strip_edition_suffix()` removes only a trailing, *delimited* edition/
  remaster/anniversary clause — `(Deluxe)`, `(Deluxe Edition)`,
  `[Remastered]`, `(2009 Remaster)`, `(Remastered 2009)`, `(25th
  Anniversary Edition)`, a trailing `` - Remastered``/`` : Remastered``
  dash/colon clause — conservative like `strip_feat_clause()`: a
  parenthetical that doesn't match the edition-keyword pattern (`(Ohia)`,
  `(Original Soundtrack)`) is never touched, since it's anchored to the
  end of the string and requires a delimiter, never firing bare
  mid-title. `normalize_album(s)` feeds the result through
  `normalize_key()` for an actual lookup/grouping key. Consumed by
  `lib.catalog.matcher`'s tiers 3/6b (the only two tiers that compare
  album strings at all) and by `organize`'s two grouping keys
  (`organize.cleanup.grouping.group_files()`,
  `organize.preimport.plan.index_existing_albums()`/`build_plan()`), so
  an edition variant of an album matches/merges against the plain
  release instead of forking into a separate group. Deliberately does
  **not** write any canonical string back to tags or rename existing
  folders — see "Cross-cutting notes" below for what's still open on
  that half.

### `lib/tags.py`
- `EXTENSIONS` — supported audio extensions.
- `sanitize(s)` — filesystem-safe path component.
- `read_tags(path)` — dict return (`artist`, `albumartist`, `album`,
  `title`, `track`, `length`, `path`) — merges the old tuple-returning
  `organize.cleanup.read_tags` and dict-returning
  `playlists.indexer._read_entry` into one function every caller uses.
- `write_tag(path, **fields)` — generalized tag writer.
- `canonical_albumartist(files)`, `dominant_album(files)`,
  `scan_audio(root, subdirs=None)`, `safe_move(src, dst)`.
- `primary_token(raw)` — narrower than `lib.text.primary_artist`, splits
  only on `&`/`/`; used specifically by `canonical_albumartist()`.

### `lib/m3u.py`
- `write_m3u8(path, entries)` — atomic write (tmp + `os.replace`); each
  entry gets a `#SPOTIFY:<track_id>` comment line plus a standard
  `#EXTINF`; paths written relative to the `.m3u8`'s own folder.
- `safe_name(name)` — filesystem-safe playlist filename.
- `read_m3u8(path)` — merges the old `playlists.m3u.parse_spotify_ids()`
  (track IDs) and `tapedeck.resolve._parse_m3u8()` (existing/missing path
  lines) into one reader returning both — `{'track_ids': [...], 'existing': [...], 'missing': [...]}`
  shape, consumed by both `playlists/` (for future reverse-sync) and
  `tapedeck/` (resolving playlist contents to mirror).

### `lib/spotify_auth.py`
Doesn't call `load_dotenv()` itself — relies on the calling `cli.py`.
- `authenticate_user()` — OAuth user-auth flow (playlists, liked songs,
  follows scopes). Token cache path is anchored (not a bare relative
  `token_cache` like the pre-refactor version).
- `authenticate_client()` — client-credentials flow (public search, no
  login), rewritten on spotipy instead of hand-rolled `requests` calls.

### `lib/catalog/`
The crate-catalog primitive — build/cache a searchable tag index of the
crate, and match an external Spotify row against it. Promoted out of
`playlists/` since `tapedeck/` needed both directly too.
- `catalog/indexer.py` — `build_index()`, `get_index()`, `save_index()`/
  `load_index()`. Calls `lib.tags.read_tags()` and `lib.paths` instead of
  its own copies.
  - `get_index()` **auto-invalidates the cache** — no longer the old
    unconditional "trust the sidecar if it exists" behavior. Before
    serving `.playlist_index.jsonl`, it runs `_is_stale()`, a cheap
    stat-only walk (`_newest_mtime()` — mtimes only, no tag reads) over
    the same tree `build_index()` covers, and rebuilds automatically if
    anything under the crate is newer than the sidecar. `--reindex`
    still works as an explicit manual override on top of this.
  - `_is_stale()` fails safe in both directions: a sidecar that's
    missing or unreadable counts as stale (forces a rebuild rather than
    serving a cache it can't actually confirm is current), while a
    `library_root` that can't be stat'd at all (permissions, a removable
    drive that dropped) counts as **not** stale — a transient
    filesystem hiccup just serves the existing cache for that run
    instead of forcing an unwanted multi-minute reindex.
  - `_newest_mtime()` stats directories as well as files, so a
    *deletion* still invalidates the cache even though a removed file
    leaves no mtime of its own to compare — removing a file bumps its
    parent directory's mtime, which the walk catches.
  - **Fixes Bug 1** (`BUGFIX_PLAN.md`): the previous version trusted the
    sidecar unconditionally once it existed, so tracks added to the
    crate after the last index build were invisible to every matcher
    tier until someone remembered to pass `--reindex` by hand — this is
    what silently produced "I Admit with Isaiah Kaleo" (and ~300 other
    tracks) landing in `unmatched.csv` despite already being in the
    crate. Confirmed fixed by re-running `playlists --apply --rescrape`
    without `--reindex` after the crate had changed.
  - Regression-tested: `tests/lib/catalog/test_indexer.py` covers add/
    delete/unchanged-crate cases against the real `get_index()`, plus a
    direct assertion (via monkeypatching `build_index`) that a rebuild
    is/isn't actually triggered, not just that the returned index looks
    right.
- `catalog/matcher.py` — `MatchIndex`, `match_rows()` (cached by Spotify
  track ID). Six-tier matching, preserved exactly: (1) exact title +
  primary-artist token, (2) exact title + any artist overlap, (3) exact
  title + exact album + duration, (4) core title (feat. clause stripped
  from the local tag) + artist overlap, (5) fuzzy title (≥0.92 ratio,
  same 4-char prefix) + duration, (6) all-symbol titles — exact raw title
  then `(album, track-number)` position. Calls `lib.text.normalize_key`/
  `normalize_title`/`primary_artist`/`split_artists` instead of its own
  regex.
  - **Album-name normalization (new):** tier 3's exact-album comparison
    and tier 6b's `by_album_track` index/lookup key both now use
    `lib.text.normalize_album()` instead of plain `normalize_key()`, so a
    Spotify row's `Album` matches a local file tagged `Album (Deluxe)`/
    `Album (2009 Remaster)` without the literal strings needing to
    agree. Tiers 1/2/4/5 never compared album at all and are unaffected.
    Verified against fixtures (not just diffed): a title+album-exact
    match where artists share no token resolves on tier 3 against an
    edition-suffixed local album tag; a symbol-only title anchored by
    `(album, track-number)` resolves on tier 6 the same way.

---

## download/

Acquisition layer. `cli.py` is a `click.group()` named `download` with
five subcommands (`export`, `spotify`, `ytdl`, `retry`, `soundbyte`);
`pyproject.toml` points `download = "download.cli:download"` at it. Calls
`load_dotenv()` once at import.

### `spotify_export.py` (was `spotify_to_csv.py`)
- `export_all_data()` — full export: `playlists.csv`,
  `playlist_tracks.csv`, `liked_songs.csv`, `spotify_manifest.csv`
  (deduped), `spotify_manifest_urls.txt`.
- `export_specific_playlist()` — one playlist by URL/ID.
- `export_playlists()` — **new**: export + merge two or more named
  playlists into a scoped `playlists_manifest.csv` +
  `playlists_manifest_urls.txt`, distinct filenames from the full-library
  export so the two don't clobber each other.
- `extract_playlist_id_from_url()` — also used by `playlists/build.py`.
- **Flagged, not fixed**: `export_specific_playlist()`'s own per-playlist
  `_urls.txt` writer doesn't filter out tracks with a blank
  `spotify_url` the way `spotify_api.export_manifest_as_txt()` does —
  a local file with no Spotify URL produces a blank line instead of
  being skipped. Found writing `TEST_PLANS.md`'s test suite for this
  file (`tests/download/test_spotify_export.py` pins it as current
  behavior); see `TODO.md`.

### `spotify_api.py` (was `spotify_utils.py`)
Everything left after auth (`lib.spotify_auth`) and normalization
(`lib.text`) moved out — purely "talk to the Spotify web API + write
CSVs."
- `get_user_playlists()`, `get_playlist_tracks()`, `get_liked_songs()` —
  paginated fetchers, sharing an extracted `_extract_track()` helper.
- `merge_and_deduplicate()` — exact dedup by Spotify track ID, then fuzzy
  dedup by `_fuzzy_key()` (a thin composite-key caller of
  `lib.text.normalize_title`/`primary_artist`, not a duplicate
  normalizer), keeping the most popular track as canonical and merging
  playlist membership.
- `export_to_csv()`, `export_manifest_as_txt(filename=...)` — filename is
  overridable so a scoped manifest doesn't clobber the full-library one.
- `get_export_dir(base_dir=None)` — thin wrapper over
  `lib.paths.exports_dir()`; CSVs now live under `PLAYLISTS_PATH/exports`.

### `spotify_download.py` (was `download_spotify.py`)
`download_spotify()` — batched spotdl download with retry and
existence-checking, dry-run/validate-only support. spotdl's exit code is
unreliable (0 even on failure), so stdout is scanned for hard-failure
markers (track genuinely gone) and soft-failure markers, each with its own
retry/logging behavior; failures logged to `failed_downloads.txt` /
`soft_failures.txt`. `--pre-skip-existing` predicts spotdl's output
filename from CSV metadata and checks it against a library index before
downloading. Uses `lib.paths.archive_path()`/`ffmpeg_path()`,
`lib.text.normalize_key()`, and `download.existing`/`download.manifest`
(below) instead of the old `organize.library` imports.

### `download/existing.py` (new)
Fast, filename-only existence check — deliberately cheaper than
`lib.catalog`'s full tag-based index, used only to skip already-downloaded
tracks before a run.
- `build_library_index()`, `scan_existing_fuzzy()` — glob-scan +
  normalized-stem matching.
- `resolve_output_dir()` — shared between `spotify_download.py` and
  `ytdl.py` (was duplicated verbatim pre-refactor).

### `download/manifest.py` (new)
Consolidates the CSV-metadata-reading + filename-prediction helpers
`spotify_download.py` and `retry.py` had each independently written.
- `predict_output_filename(artist, track, fmt)`, `read_csv_metadata(path)`
  — delimiter-sniffing, requires `track_name`/`artist_names` columns,
  first-seen-wins across multiple files. `read_csv_metadata()` always
  returns a dict (never `None`). Each value is a dict with `artist`,
  `track`, and `album` keys (the old pre-refactor version returned
  `(artist, track)` tuples with no album field — `album` was added so
  `retry.py --report-csv` has something to put in its `album` column).
- `sanitize_filename(filename)` — strips the same characters spotdl's
  own writer strips, carried over verbatim from the old
  `spotify_download.py`'s copy; `predict_output_filename()` is a thin
  wrapper over it.
- **Caveat, unverified**: this file did not actually exist post-refactor
  despite being documented above as already consolidated — it was
  reconstructed after the fact from the old pre-refactor logic and the
  shapes its two call sites expect. The `album` field specifically is a
  best-effort guess at the CSV column name (`album_name`, falling back
  to `album`) that hasn't been checked against a real export header. See
  `TODO.md`'s open follow-ups.

### `ytdl.py` (was `yt_dlp_downloader.py`)
`download_ytdl()` — single track, set/playlist, or album from any
yt-dlp-supported URL. Single vs. playlist use separate output templates
(Windows' null-byte handling corrupts the conditional template). Shares
`download.existing.resolve_output_dir()` and
`lib.paths.ffmpeg_path()` (imported as `resolve_ffmpeg_path` to avoid
shadowing the CLI's own `--ffmpeg` parameter) with `spotify_download.py`.
`is_playlist_url()` — regex-based playlist/set detection.
`AUDIO_FORMATS` — the format choice list the CLI validates against.

### `retry.py` (was `retry_failures.py`)
Rebuilt from the README description — the original source was lost.
`run_retry()`:
- Unions `failed_downloads.txt` + `soft_failures.txt`, deduping URLs and
  unioning reasons.
- Excludes `track_unavailable` (hard failure) by default;
  `include_unavailable=True` keeps them.
- `no_check=True` skips the library re-check.
- Default: re-checks remaining URLs against the library using the same
  exact-match path `spotify_download.py --pre-skip-existing` uses
  (predict filename from CSV metadata → normalize → check against
  `download.existing`'s index), so the retry list is consistent with what
  a real run would itself skip.
- `report_csv_path` — writes the manual-hunt sheet (`artist, track,
  album, reason, spotify_url, search`), sorted artist → album → track,
  with a clickable YouTube search link per row.
- Returns a full breakdown dict (`total_seen`, `hard_excluded`,
  `already_on_disk`, `no_meta`, `retry_urls`, `output_path`,
  `report_csv_path`) — `cli.py` always prints the summary from it, no
  separate verbose mode.
- `DEFAULT_FAILED`, `DEFAULT_SOFT`, `DEFAULT_OUT` — default log/output
  paths. `DEFAULT_REPORT` exists but is currently unused —
  `--report-csv` requires an explicit path.

**Post-refactor correction**: the module as originally written was
missing `import re` despite using `re.compile()` at module level for
`_LOG_LINE_RE` — an import-time failure that wouldn't surface until the
command was actually run. Fixed; flagged here since this file has no
pre-refactor original to diff against, so it's the least-verified module
in `download/` (see `TEST_PLANS.md` §2 for the regression tests this
warrants).

### `soundbyte.py` (was `soundbyte_albums.py`)
Pulls top-N albums from a Firebase Firestore collection, searches Spotify
for each, exports album- and (optionally expanded) track-level manifests.
- `authenticate_client()` from `lib.spotify_auth` replaces the old
  hand-rolled `requests`-based client-credentials flow — this also
  changed `search_spotify_album()`/`fetch_album_tracks()` to use
  `sp.search()`/`sp.album()`/`sp.next()` instead of raw HTTP calls;
  behavior (progressively loosened search queries, exact-title
  preference, paginated track fetch) is preserved.
- `run_soundbyte(limit, output_dir, delay)` — single orchestrating entry
  point (fetch → enrich → album export → track expand → track export),
  matching `retry.run_retry()`'s shape. Returns album/track CSV paths and
  match counts.
- Requires `firebase-admin`, `FIREBASE_PROJECT_ID` +
  `FIREBASE_CREDENTIALS_PATH` in `.env`.

### `download/cli.py`
Single `click.group('download')`. Commands and their notable options:
`export` (`-p/--playlist` repeatable, `--playlists-file`, `-o/--output`,
`--mine`), `spotify` (`-u/--url-file`, `-o/--output`, `-f/--format`,
`-b/--bitrate`, `--overwrite-errors`, `--skip-existing`,
`--validate-only`, `--batch-size`, `--retries`, `--retry-delay`,
`--pre-skip-existing`, `--cookies-from-browser`, `--cookie-file`,
`--debug`), `ytdl` (positional URL, `-o/--output`, `-f/--format`,
`--quality`, `--no-thumbnail`, `--overwrite`, `-v/--verbose`,
`--metadata-only`, `--cookies-from-browser`, `--ffmpeg`), `retry`
(`--failed-log`, `--soft-log`, `-o/--output`, `--include-unavailable`,
`--no-check`, `--metadata-source`, `--library-root`, `--report-csv`),
`soundbyte` (`--limit`, `-o/--output`, `--delay`).

---

## organize/

Takes raw downloads and turns them into a clean, beets-managed crate.

### `cleanup.py`
The regroup-in-place **policy** only now (the toolkit half moved to
`lib.tags`/`lib.text`). Repairs two beets import failure modes: albums
split into per-track-artist folders (no `albumartist` tag on import), and
whole albums scattered as loose singletons. Regroups straight off file
tags, independent of beets/beets.db.
- `resolve_crate(cli_value=None)` — `ARCHIVE_PATH`, **required, no
  fallback** — deliberately stricter than `lib.paths.archive_path()`'s
  `~/music/tapebuilding` default, since this command moves files and
  rewrites tags.
- `group_files()`, `build_plan()`, `prune_empty_dirs()`, `rebuild_db()`,
  `run_cleanup()` (the plain entry point `cli.py` calls). (Current source
  location is `organize/cleanup/grouping.py` post-split — see the "still
  needs updating" note under Cross-cutting notes; this section is
  otherwise describing the pre-split `cleanup.py` layout.)
- **Album-name normalization (new):** `group_files()`'s grouping key is
  now `(normalize_album(album),)` instead of `(normalize_key(album),)` —
  see `lib/text.py`'s new `normalize_album()`/`strip_edition_suffix()`.
  A track tagged `Album` and one tagged `Album (Deluxe)`/`Album (2009
  Remaster)` now land in the same group; `canonical_albumartist()`/
  `dominant_album()` then pick the folder name/tag from whichever raw
  string is more common across the merged group, same majority-vote
  behavior as any other tag disagreement — no new canonical string is
  invented at grouping time. Verified against a fixture (not just
  diffed): two tracks tagged `Title`/`Title (Deluxe)` merge into one
  `Artist - Title` destination folder. Deliberately *not* extended to
  `resplit_plan.py`'s naming or to writing a canonical album string back
  to existing folders/tags — see `TODO.md`'s open items for both.
- `--rebuild-db` deletes and rebuilds `beets.db` via an as-is (no
  MusicBrainz) reimport. Flags plausible wrong-merges (unusually large
  album groups) and VA-filed albums in the dry-run summary.
- Idempotent.
- **Fixes Bug 2** (`BUGFIX_PLAN.md`): grouping is now artist-aware, not
  just album-title-based. `build_plan()` calls the new
  `is_unrelated_va_collision(aa, members)` right after computing
  `canonical_albumartist()` — true only when that call resolved to
  `'Various Artists'` by fallback (no majority/dominant collaborator),
  no member's own `albumartist` tag actually says Various Artists/VA
  (checked via `_is_explicit_va()`), and the group is exactly two
  tracks whose artist tokens (`shares_artist_token()`, unioning
  `artist`+`albumartist` per file, split/normalized via
  `lib.text.split_artists`/`normalize_key`) share nothing in common.
  That combination — e.g. `Anysia Kym - Automatic` and `Spencer. -
  Automatic`, two unrelated singles that happen to share a title — is
  now filed as two singletons instead of merged into one `Various
  Artists - Automatic` folder. Deliberately scoped to exactly two
  members: a 3+ track group with no full overlap still falls through
  to the existing ambiguous-VA flagging (now reported separately from
  the new `split_groups` count) rather than being auto-split, since
  that broader case hasn't been confirmed as the same pattern. A
  genuine collab album (any shared artist token) or an explicitly
  VA-tagged compilation still merges exactly as before.
  `organize.preimport.stage()`'s `build_plan()` imports and applies the
  same `is_unrelated_va_collision()` check (before its existing-folder
  merge lookup, so a confirmed collision can't merge into an unrelated
  real VA folder either) — one shared decision, not a second copy.
- **Resplit mode (Bug 2's other half)**: *Retired as of Phase 4*.
  This opt-in repair mode for fixing pre-existing wrong merges was
  superseded by the improved grouping logic in `cleanup --apply` runs.
  The forward-looking `is_unrelated_va_collision()` check now prevents
  new wrong merges, making resplit unnecessary for ongoing maintenance.
  See `BUGFIX_PLAN.md` for the Phase 4 completion details.
- **Phase 6 (tests + documentation)**: *Completed*.
  Comprehensive idempotency test updated and verified, covering all
  edge cases from TODO.md. All organize tests passing. Documentation
  updated to reflect current system state post-refactor.

### `preimport.py`
Runs the same regrouping logic **before** beets ever sees the drop.
- `stage()` — called automatically by `beets_import.run_import()` unless
  `--no-preimport`. Three outcomes per album-tag group: merge into an
  existing crate album folder, stage a new folder under
  `<input>/albums/`, or pass through as a singleton.
- `index_existing_albums()` — collision across ≥2 existing folders with
  the same normalized key marks it ambiguous (refuses the merge rather
  than risking binding two different real albums).
- Returns a `report` dict (`staged_folders`, `merged_folders`,
  `merged_tracks`, `duplicates`, `ambiguous`, `singletons`, `tag_writes`)
  that `beets_import.py` consumes.
- Only `group_files`/`resolve_crate`/`is_unrelated_va_collision` still
  come from `organize.cleanup` (deliberately organize-specific policy,
  shared with `cleanup.py`'s own regroup-in-place pass rather than
  duplicated); everything else imports directly from `lib.tags`/
  `lib.text`. (Current source location is `organize/preimport/plan.py`
  post-split, same caveat as `cleanup.py` above.)
- **Album-name normalization (new):** `index_existing_albums()`'s key
  and `build_plan()`'s merge-target lookup key both now use
  `lib.text.normalize_album()` for the album half instead of plain
  `normalize_key()`, so an incoming download tagged `Album (Deluxe)`
  merges straight into an existing crate folder for the plain `Album`
  release rather than staging a sibling folder that resplit would later
  have to untangle. Verified against a fixture (not just diffed): an
  existing `Artist - Title` crate folder correctly absorbs an incoming
  track tagged `Title (Deluxe)` via `merged_moves` with zero
  `staged_moves`.

### `beets_import.py`
Two-pass beets importer: pass 1 groups multi-track albums and matches
against MusicBrainz; pass 2 imports remaining loose tracks as singletons.
- `run_import(input_dir, output_dir=None, dry_run=False, only_pass=None, timid=False, no_preimport=False, no_merge_existing=False, verbose=False)`
  — the plain entry point. `output_dir` resolution is **required, no
  fallback**: calls `lib.paths.resolve('ARCHIVE_PATH', required=True)`
  directly, matching `resolve_crate()`'s strictness exactly (both move
  files on disk).
- `_album_pass_target()` — when preimport ran, the album pass targets
  only `<input>/albums/` (what preimport just staged), skipped entirely
  if nothing was staged — never falls through to a flat directory of
  loose singletons.
- `_warn_singles_after_albums()`, `export_library_csv()`,
  `print_library_stats()`.
- Runs `organize.preimport.stage()` automatically before both passes
  unless `--no-preimport`.

### `normalize_artists.py`
A beets plugin (not a CLI tool) — normalizes artist/albumartist strings
at import time into `"A, B & C"` form, handling `feat.`/`ft.`, collab
`x`, and `and`. Untouched by the refactor. Registered via `config.yaml`'s
`plugins` list + `pluginpath`.

### `config.yaml` / `config.yaml.example`
Beets configuration; the example is a path-templated version of the real
(machine-specific, gitignored) config.

### `organize/cli.py`
`click.group('organize')` with `import` and `cleanup` subcommands, plus
`--export-csv` under `import`. See `README.md` for exact usage.

---

## playlists/

Builds and maintains local `.m3u8` files from Spotify playlists, resolving
each track to a file in the crate. Most mature subsystem — tiered fuzzy
matching (now `lib.catalog.matcher`), cached crate index (now
`lib.catalog.indexer`), atomic file writes (now `lib.m3u`).

### `build.py`
Orchestrates export (optional rescrape) → track/playlist selection →
catalog matching → `.m3u8` writing → unmatched handoff.
- `build_playlists(apply=..., rescrape=..., names=..., covers=..., verbose=..., playlists_path=..., archive_path=..., exports_dir=..., reindex=...)`
  — main entry, called directly by `core.sync.run_sync()` and by
  `core.download_songs.run_download_songs()`'s playlists step.
- `_select_playlists()` — `-p/--playlist` (name or ID, repeatable)
  overrides `--all`/`--mine` (default: owned playlists only).
- `_scope_rescrape()` — with `--rescrape` + `-p`, fetches and patches in
  only the named playlist(s)' rows instead of a full re-export.
- `_write_unmatched()` — non-fatal, atomic write of `unmatched.csv` +
  `unmatched_urls.txt` (feeds back into `download spotify -u`).
- `_select_playlists()`'s default scope (no `--all`, no `-p`) filters
  `playlists.csv` rows to `owner_id == os.getenv('SPOTIFY_USER_ID')`,
  warning and falling back to "build everything" if `SPOTIFY_USER_ID` is
  unset. `owner_id` is a dedicated column in `PLAYLIST_META_FIELDS`,
  populated by both `download.spotify_api.get_user_playlists()` and
  `build.py`'s own `_scope_rescrape()`. Previously this compared against
  the display-name `owner` column instead and could never match even
  with `SPOTIFY_USER_ID` set correctly — fixed; see `TODO.md`. Playlists
  exported before the fix won't have `owner_id` populated until
  re-exported.
- Imports `lib.spotify_auth.authenticate_user`, `lib.paths`,
  `lib.catalog.indexer.get_index`, `lib.catalog.matcher`, `lib.m3u` — plus
  the one deliberately-kept cross-package dependency,
  `download.spotify_api`/`download.spotify_export` (auth + export
  really do belong to `download`).

### `playlists/cli.py`
Single `click.command('playlists')` (not a group — one operation, several
flags): `--apply`, `--all`, `--mine` (only present to error clearly if
combined with `--all`), `-p/--playlist` (repeatable), `--rescrape`,
`--covers`, `--reindex`, `--verbose`, `-o/--playlists-path`,
`--archive-path`, `--exports-dir`. See `README.md` for full usage.

---

## tapedeck/

Mirrors a rotation subset of the crate 1:1 by crate-relative path into a
sync target (`TAPEDECK_PATH`). No downloading, no Spotify — a copy/hardlink
of a slice of the crate that already exists.

### `resolve.py`
Turns a `(kind, spec)` pair into crate paths to stage — `kind` is one of
`album`/`song`/`soundtrack`/`playlist`, `spec` is a crate-relative path or
a name resolved against the crate.
- Returns four buckets: `folders`, `files`, `m3u8`, `warnings`.
- `need_index_for()` — skips building the (potentially expensive) crate
  index whenever a spec doesn't actually need it (path-form specs,
  soundtrack/playlist kinds, album-by-folder-basename).
- Uses `lib.text.normalize_key`/`split_artists` and
  `lib.m3u.read_m3u8()` directly (replaced its own private `_parse_m3u8()`
  — one of the two duplicate m3u8 readers `lib.m3u` was written to
  replace).
- No `cli.py`-bound pieces — pure resolution logic.

### `copy.py`
Generic stage/unstage over the four resolved buckets.
- `stage()` — copies (default) or hardlinks (`--link`, same-volume only);
  skips existing destinations unless `--overwrite`.
- `unstage()` — inverse, prunes now-empty parent directories.
- Playlist unload is **refcounted**: a file is removed only if no other
  staged `.m3u8` under `tapedeck/playlists/` still references it — scoped
  to playlists only, so unloading a playlist can still punch a hole in an
  independently-loaded album copy sharing the same track (documented
  sharp edge).
- Uses `lib.m3u.read_m3u8()` (`['existing']`) instead of a private
  cross-file import of `resolve.py`'s old parser.

### `deck.py`
- `_maybe_index()` — fetches the cached crate index + matcher only when
  `need_index_for()` says the invocation needs it.
- `load_tapedeck()` / `unload_tapedeck()` / `list_tapedeck()` — resolve →
  summarize → stage/unstage, dry-run-by-default. `unload_tapedeck()`
  doesn't pass a `reindex` kwarg (matches the old CLI's lack of an
  `--reindex` flag on unload — a latent `AttributeError` here in the
  pre-refactor argparse version was fixed during the split:
  `_maybe_index()` now takes `reindex` as an explicit kwarg with a
  default instead of unconditionally reading a possibly-undefined arg).
- `_fmt_size()` — human-readable size formatting for `list`.
- Uses `lib.paths` directly (`archive_path`/`tapedeck_path`/
  `playlists_path`/`exports_dir`); `playlists_root()` inlines the old
  `tapedeck/paths.py`'s graceful-degradation behavior (swallows the
  "`PLAYLISTS_PATH` unset" error and returns `None`, since playlists
  aren't required for album/song/soundtrack loads).
- Imports `lib.catalog.indexer.get_index`/`lib.catalog.matcher.MatchIndex`
  directly — no remaining dependency on `playlists/`.

### `tapedeck/cli.py`
`click.group('tapedeck')` with three subcommands. `load KIND SPEC...` —
`--apply`, `--link`, `--overwrite`, `--reindex`, `--verbose`,
`--archive-path`, `--tapedeck-path`, `--playlists-path`, `--exports-dir`.
`unload KIND SPEC...` — same shape minus `--link`/`--overwrite`/
`--reindex` (not meaningful for a removal). `list` — `--kind`,
`--tapedeck-path`, `--verbose`. `KIND` is one of `album`/`song`/
`soundtrack`/`playlist` for `load`/`unload`. Deviation from the old
argparse version: `unload` no longer accepts the old suppressed, unused
`--overwrite`/`--exports-dir` (kept only "for parity" with `load`'s
parser pre-refactor, never actually read by `_unload`) — dropped instead
of carried forward as dead options. See `README.md` for full usage.

---

## core/

Opinionated multi-step workflows over the four domain packages above, now
in-process (no subprocess/CLI shelling).

### `download_songs.py`
`run_download_songs(source=None, apply=False, archive_path_opt=None, drop=None, only=None, format='mp3', bitrate='320k', verbose=False)`
— download → beets-import → playlists-refresh in one pass.
- `_resolve_source()` — accepts an existing file/dir, or a bare Spotify
  URL (written to a temp one-line `.txt`).
- Dry-run: each step runs for real in its own no-op mode instead of being
  skipped — `download_spotify(..., validate_only=not apply)`,
  `run_import(..., dry_run=not apply)`, `build_playlists(apply=apply, ...)`.
  Deliberate behavior change from the old subprocess version, which ran
  nothing at all in dry-run.
- Returns `{'steps': [{'step', 'ok', 'error', 'skipped'}, ...], 'ok': bool}`
  — this module's own step-summary shape, not real per-step counts (the
  three domain functions don't expose those yet).
- `--verbose` forwards to `download_spotify(..., debug=verbose)` —
  confirmed correct: `download.cli`'s own `spotify` subcommand has no
  separate `--verbose`, only `--debug`, mapped the same way.

### `sync.py`
`run_sync(names=None, covers=False, verbose=False, playlists_path=None, archive_path=None, exports_dir=None)`
— thin promotion of the `playlists --apply --rescrape` flow into a real
function, calling `build_playlists()` directly. No dry-run of its own —
for a preview, call `build_playlists(apply=False, ...)` directly.

### `core/cli.py`
`click.group('core')` with `download-songs` and `sync` subcommands.
Neither subcommand function calls `sys.exit()` itself — `cli.py`
translates `ok: False` / raised exceptions into exit codes.

---

## Cross-cutting notes (resolved during the refactor)

- **One normalization tier system** (`lib.text`) replaces four
  independent copies; **one root-resolution function** (`lib.paths.resolve`)
  replaces four independent copies; **one tag reader** (`lib.tags.read_tags`)
  replaces two; **one m3u8 reader** (`lib.m3u.read_m3u8`) replaces two;
  **one pair of Spotify auth flows** (`lib.spotify_auth`) replaces two
  independent implementations. **One album-identity function**
  (`lib.text.normalize_album`/`strip_edition_suffix`, new) is now the
  single place edition-suffix collapsing happens — `lib.catalog.matcher`
  (tiers 3/6b), `organize.cleanup.grouping.group_files()`, and
  `organize.preimport.plan.index_existing_albums()`/`build_plan()` all
  call it rather than each growing its own suffix-stripping regex.
- **Dependency graph**, now: every domain package may depend on `lib/`;
  `core/` may depend on any domain package; the one remaining
  domain-to-domain dependency is `playlists → download` (auth + export),
  confirmed as the only one left after a full-repo grep.
- **Dual-case env vars are gone.** Every root is one canonical uppercase
  name, resolved in `lib/paths.py` alone. `ARCHIVE_PATH`/`PLAYLISTS_PATH`/
  `TAPEDECK_PATH`/`FFMPEG_PATH` — see `README.md`'s environment variables
  section for the full list including Spotify/Firebase creds.
- **Strictness on file-moving operations is deliberate and consistent**:
  `organize.cleanup.resolve_crate()` and `organize.beets_import.run_import()`
  both require `ARCHIVE_PATH` with no fallback, unlike `lib.paths.archive_path()`'s
  convenience default used elsewhere (read-mostly contexts like
  `download/`'s existence checks).
- **Organize-matcher key relationship**: `organize`'s grouping keys and
  `lib.catalog.matcher`'s album-keyed tiers (3, 6b) both use
  `lib.text.normalize_album()` for album identity, ensuring that
  "Title" and "Title (Deluxe)"/"Title (2009 Remaster)" resolve to the
  same identity in both systems without requiring literal string matches.
- **Documented-as-done is not the same as actually-done.** Post-refactor
  smoke testing found three import-breaking gaps between this document
  and the real source (`download.existing.resolve_output_dir()` missing,
  `download/manifest.py` missing entirely, `retry.py` missing `import
  re`) — all three sat undetected because nothing had actually run the
  affected command paths, only reviewed/written the docstrings
  describing them. See `TODO.md`'s "Fixed this session" log for the
  specifics and `NEW_FEATURE_GUIDE.md` §5 for the "actually run it"
  checklist this motivated. `TEST_PLANS.md` lays out the test suite
  (starting with cheap import smoke tests) meant to catch this class of
  bug going forward instead of relying on manual `uv run` testing.
