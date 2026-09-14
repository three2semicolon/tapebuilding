# tapebuilding — test plan

What needs test coverage and why, organized by package. This is a plan,
not test code — build `tests/` from this once the shape looks right.
Priority order matters here: sections are ordered by how much would
break silently (or loudly, but expensively) if left uncovered.

Context: three of the bugs found while smoke-testing commands by hand
this session (`download.existing` missing `resolve_output_dir`,
`download.manifest` not existing at all, `retry.py` missing `import re`)
were all **import-time failures** — every one of them would have been
caught by the cheapest possible test (importing the module) without
needing to know anything about what the code inside actually does. That's
why import smoke tests are section 0, not an afterthought.

---

## 0. Import smoke tests — do these first

**Why:** every command in this project failed this session not because
of wrong logic, but because a documented-as-done function didn't
actually exist in the file, or an import was missing. A test that does
nothing but `import` a module and call its console-script entry point
with `--help` would have caught all three bugs in seconds instead of
one `uv run` failure at a time.

- [ ] `import download.cli`, `import organize.cli`, `import playlists.cli`,
  `import tapedeck.cli`, `import core.cli` — top-level import of every
  package's cli module.
- [ ] `import download.existing`, `download.manifest`, `download.retry`,
  `download.spotify_download`, `download.spotify_export`,
  `download.spotify_api`, `download.ytdl` — every module `cli.py`
  transitively imports, tested directly too (a module can import fine
  via one path and fail via another if there's a circular or
  conditional import).
- [ ] `import lib.paths`, `lib.text`, `lib.tags`, `lib.m3u`,
  `lib.spotify_auth`, `lib.catalog.indexer`, `lib.catalog.matcher`.
- [ ] For each console script (`download`, `organize`, `playlists`,
  `tapedeck`, `core`) and each subcommand: invoke with `--help` via
  Click's `CliRunner` and assert exit code 0. This exercises the actual
  installed-entry-point path (`pyproject.toml`'s `[project.scripts]`),
  not just a bare `import`.

This section alone would have shortened this session's debugging loop
from three separate manual `uv run` failures to one `pytest` run.

---

## 1. `lib/` — shared foundation

Everything downstream depends on this being right, and it's almost
entirely pure functions — cheapest tests in the repo per unit of
confidence gained.

### `lib/text.py`
**Why:** consolidates four independent pre-refactor normalization
copies into one; `lib.catalog.matcher`'s six-tier matching and
`download.manifest`'s existence-check path both depend on it agreeing
with itself everywhere it's called.
- `normalize_key()` — case, punctuation, whitespace collapsing.
- `normalize_title()` — feat./ft./featuring clause stripping,
  parenthetical stripping, on top of `normalize_key()`.
- `primary_artist()` — first credited artist from `"A, B & C"` /
  `"A feat. B"` forms.
- `split_artists()` — full artist list from the same strings.
  **Specifically test that a bare `" and "` is NOT treated as a
  separator** — this is a documented, deliberate difference from
  `organize/normalize_artists.py`'s beets plugin (which does split on
  `and`). A future "fix" that makes these consistent would be a
  regression against an intentional design decision; a test pinning the
  current behavior is what prevents that.

### `lib/paths.py`
**Why:** the one place env-var resolution happens; the
strict-vs-convenience-default split between root resolvers is a
deliberate safety property (file-moving operations should error loudly
on a missing path, not guess).
- `resolve()` — precedence order `cli` > `os.environ` > `default`;
  raises `ValueError` when `required=True` and nothing resolves.
- `archive_path()` — has a fallback default (`~/music/tapebuilding`).
- `playlists_path()` — **no fallback, required** — test that a missing
  `PLAYLISTS_PATH` actually raises rather than silently defaulting.
- `tapedeck_path()` — has a fallback default.
- `exports_dir()` — creates the directory if missing; test both the
  explicit-`cli`-path branch and the derived-from-`playlists_path()`
  branch separately, since they're different code paths in the source.
- `ffmpeg_path()` — no default, `None` is a valid "let the tool find it
  on PATH" return, not an error.

### `lib/tags.py`
- `read_tags()` — dict shape (`artist`, `albumartist`, `album`, `title`,
  `track`, `length`, `path`) against a real tagged fixture file.
- `sanitize()` — filesystem-unsafe character stripping.
- `canonical_albumartist()`, `dominant_album()` — majority-vote logic
  across a folder of files with slightly inconsistent tags.
- `primary_token()` vs `lib.text.primary_artist()` — **test that these
  two deliberately differ** (`primary_token` only splits on `&`/`/`).
  Same reasoning as `split_artists()` above: pin the intentional
  divergence so it isn't "fixed" into sameness later.

### `lib/m3u.py`
- `write_m3u8()` — atomicity (tmp file + `os.replace`, no partial file
  left behind on a simulated failure), relative-path-per-entry
  correctness, `#SPOTIFY:<id>` comment format.
- `read_m3u8()` — round-trip against `write_m3u8()`'s own output, and
  separately against a hand-written `.m3u8` to check the
  `{'track_ids', 'existing', 'missing'}` split is correct when some
  referenced files don't exist on disk.

### `lib/catalog/indexer.py`
**Why:** caching logic (`get_index()`) is easy to get subtly wrong —
stale-cache bugs are the classic failure mode here.
- `build_index()` against a small fixture crate.
- `get_index()` — cache hit vs miss vs `--reindex` forced rebuild;
  assert the sidecar file's mtime/content actually changes on rebuild
  and doesn't on a cache hit.

### `lib/catalog/matcher.py`
**Why:** this is the actual "does a Spotify track equal a file on disk"
brain shared by `playlists/` and `tapedeck/` — false positives silently
mis-file tracks, false negatives silently orphan them into
`unmatched.csv`.
- One test per tier (1 through 6), each constructed so **only that
  tier** would match — i.e. tier-1 (exact title + primary artist)
  shouldn't be tested with data that would also satisfy tier-3, or a
  regression that breaks tier ordering wouldn't be caught.
- Tier 6 specifically (all-symbol titles, position-based fallback) —
  easy to under-test since it's rare in practice but exists precisely
  for the tracks other tiers can't handle.

---

## 2. `download/`

### `download/manifest.py` — highest priority in this package
**Why:** this file didn't exist at all until this session — it was
documented in `PACKAGE_OVERVIEW.md` as already consolidated, but the
actual module was never created, and nothing caught that until a manual
`uv run` hit the `ImportError`. It's reconstructed from the old
pre-refactor `spotify_download.py`'s logic plus the shapes its two real
call sites (`spotify_download.py`, `retry.py`) expect — it has **not**
been verified against real export CSVs.
- `sanitize_filename()` — test against actual characters spotdl is
  known to strip; if this drifts from spotdl's real behavior even
  slightly, every `--pre-skip-existing` check silently miscounts.
- `predict_output_filename()` — exact string shape (`"Artist -
  Track.ext"`) matches a real spotdl-downloaded filename on disk, not
  just the function's own internal logic.
- `read_csv_metadata_from_file()` — **verify the `album` field against
  a real `spotify_manifest.csv`/`playlists_manifest.csv` header.** The
  current implementation guesses `album_name` or falls back to `album`
  — if neither matches the real column name, every `album` field
  silently comes back empty (not an error, just wrong data feeding
  `retry.py`'s `--report-csv`). This is the single highest-value fixture
  test to write in this whole plan.
- `read_csv_metadata_from_file()` — missing `track_name`/`artist_names`
  columns returns `{}` (whole-file rejection), not a partial dict.
- `read_csv_metadata()` — directory mode: first-seen-wins across
  multiple CSVs with an overlapping URL.

### `download/existing.py`
**Why:** `resolve_output_dir()` was also missing until this session —
same "documented but not implemented" failure mode as `manifest.py`,
just caught one command earlier.
- `resolve_output_dir()` — `cli`-arg override vs `ARCHIVE_PATH` env
  fallback; directory actually gets created (`os.makedirs`) when it
  doesn't exist yet — this specifically matters for `download ytdl`
  against a brand-new output path, which is exactly the case that
  surfaced in this session's testing.
- `build_library_index()` — extension filtering (only `lib.tags.EXTENSIONS`),
  `__pycache__` exclusion, empty/missing-root graceful return.
- `scan_existing_fuzzy()` — normalization-based match against a
  library index built with slightly different casing/punctuation than
  the candidate filenames (the actual scenario this function exists
  to handle).

### `download/spotify_export.py` + `download/spotify_api.py`
- `merge_and_deduplicate()` — exact dedup by Spotify track ID, then
  fuzzy dedup by the composite key, keeping the **most popular** track
  as canonical when duplicates collide — test with two near-duplicate
  rows (remaster/regional version) where popularity differs, and assert
  the right one survives.
- `export_playlists()` — scoped multi-playlist export writes
  `playlists_manifest.csv`/`_urls.txt`, **not**
  `spotify_manifest.csv`/`_urls.txt` — test the filenames don't clobber
  a pre-existing full-library export in the same directory.
- `extract_playlist_id_from_url()` — a handful of real Spotify URL
  shapes (track, album, playlist, with/without query params).

### `download/spotify_download.py`
- `_check_existing()` / `--pre-skip-existing` path — end-to-end against
  a fixture CSV + fixture "library" directory, asserting the
  existing/new/no_meta counts match expectations exactly.
- `--validate-only` — returns early without attempting any download.
- Batch splitting (`batch_size`) — correct number of batches for
  edge-case counts (exact multiple, remainder, single URL).
- Soft vs hard failure classification — feed canned spotdl stdout
  containing each `SOFT_FAILURE_PATTERNS`/`HARD_FAILURE_PATTERNS`
  string and assert the right log file gets the URL (`soft_failures.txt`
  vs `failed_downloads.txt`), and that a hard failure does **not**
  retry while a soft one does (up to `retries`).
- URL deduplication preserves first-seen order.

### `download/ytdl.py`
- `is_playlist_url()` — the `_PLAYLIST_RE` regex against real
  `/sets/`, `/albums/`, `/tracks/`, `/likes/`, `/reposts/` URLs and a
  plain non-playlist URL, to pin exactly what does and doesn't count.
- Single vs. playlist output template selection based on
  `is_playlist_url()`.
- `--metadata-only` — lists tracks without invoking a real download
  (mock `yt_dlp.YoutubeDL`).

### `download/retry.py` — second-highest priority in this package
**Why:** entirely rebuilt from the README description this session
(the original source was lost) — it has no prior implementation to
diff against, only a docstring's description of intended behavior, and
it wasn't exercised end-to-end before the `import re` bug was found by
inspection rather than by running it.
- `read_failure_log()` — parses `url  # reason` and bare-`url` lines;
  ignores blank lines.
- `collect_failures()` — unions two failure logs, deduping URLs and
  **unioning reasons** (a URL appearing as `LookupError` in one file and
  `track_unavailable` in the other should end up with both reasons in
  its set).
- Hard-exclusion logic — a URL with `track_unavailable` in its reason
  set is excluded by default, kept with `--include-unavailable`.
- The re-check path — must use the exact same
  predict-filename-then-normalize-then-check-library-index sequence as
  `spotify_download.py --pre-skip-existing`, so **the real regression
  test here is a shared-fixture test**: run both `_check_existing()`
  (from `spotify_download.py`) and `run_retry()`'s internal check
  against the identical CSV + library fixture and assert they agree on
  which URLs are "already on disk."
- `no_meta` handling — a URL with no CSV metadata is kept in the retry
  list rather than silently dropped (can't verify it's already
  downloaded without metadata).
- `--report-csv` — row shape, sort order (`artist` → `album` → `track`,
  case-insensitive), and that the YouTube search link is correctly
  URL-encoded.
- Import smoke test specifically for this file even though it's covered
  in section 0 — this is the module where an import bug (missing
  `import re`) sat undetected the longest.

---

## 3. `organize/`

### `organize/preimport.py`
**Why:** runs automatically before both beets passes; a wrong decision
here (merge vs new-folder vs singleton) means beets sees the wrong
input and there's no beets-level safety net for that.
- `stage()` — one test per outcome (merge into existing album folder,
  new staged folder, singleton passthrough).
- `index_existing_albums()` — **ambiguous-collision test**: two existing
  folders with the same normalized key should refuse the merge rather
  than guessing, and this refusal should show up in the `ambiguous`
  bucket of the returned report, not silently pick one.

### `organize/beets_import.py`
- `_album_pass_target()` — targets only `<input>/albums/` when
  preimport staged something; **skipped entirely (no fallback to a flat
  directory) when nothing was staged** — this "never falls through"
  behavior is explicitly called out in the docs as a fixed bug, so it's
  worth a regression test specifically for the empty-staging case.
- `run_import()` — `ARCHIVE_PATH` required-no-fallback behavior (should
  raise, not guess a directory) — same strictness family as
  `organize.cleanup.resolve_crate()`, worth testing both together so a
  future change can't loosen one without the other.

### `organize/cleanup.py`
- Idempotency — running `run_cleanup()` twice on the same crate produces
  no changes the second time.
- Wrong-merge flagging — an unusually large album group in the dry-run
  summary.
- VA-filed album detection in the dry-run summary.
- `resolve_crate()` — required, no fallback (same pattern as
  `beets_import.run_import()` above).

---

## 4. `playlists/`

### `playlists/build.py`
**Why:** most mature subsystem, but has a **known, documented,
unfixed bug**: `_select_playlists()`'s default scope filters by
`playlists.csv`'s `owner` column, which is a Spotify **display name**,
not the `SPOTIFY_USER_ID` env var it's compared against — meaning the
default "just my playlists" scope may silently fall through to
"build everything" instead.
- **Write this as a currently-failing (expected-fail / xfail) test
  first**, asserting that with `SPOTIFY_USER_ID` set to a real user ID
  and a fixture `playlists.csv` where `owner` is a display name for that
  same user, `_select_playlists()`'s default scope returns only that
  user's playlists. This documents the bug as a test rather than a
  comment, and flips to a real pass the moment it's fixed — don't build
  new features on top of assuming this already works.
- `_scope_rescrape()` — with `-p` + `--rescrape`, only the named
  playlist(s)' rows get patched, not a full re-export.
- `_write_unmatched()` — atomic write, non-fatal (a write failure here
  shouldn't abort the whole `build_playlists()` run).
- End-to-end against a small fixture: fixture Spotify export CSVs +
  fixture crate → correct `.m3u8` output + correct `unmatched.csv`.

---

## 5. `tapedeck/`

### `tapedeck/resolve.py`
- `need_index_for()` — returns `False` for path-form specs,
  soundtrack/playlist kinds, and album-by-folder-basename; `True`
  otherwise. Worth testing directly since it's a performance-relevant
  gate (skips building the crate index when unnecessary) and a wrong
  answer either wastes time or silently under-resolves.
- Resolving each of the four `kind`s (`album`/`song`/`soundtrack`/
  `playlist`) against fixture data → correct `folders`/`files`/`m3u8`/
  `warnings` buckets.

### `tapedeck/copy.py`
- `stage()` — copy vs `--link` (same-volume hardlink) branches;
  `--overwrite` behavior.
- `unstage()` — **refcounting test**: load two playlists that share a
  track, unload one, assert the shared track is *not* removed; unload
  the second, assert it *is* removed. Also test the documented sharp
  edge — a track independently loaded via `load album`/`load song` and
  also referenced by an unloaded playlist should **not** be removed by
  the playlist unload (refcounting is scoped to playlists only).
- Empty-parent-directory pruning after `unstage()`.

### `tapedeck/deck.py`
- `_maybe_index()` — only builds the index when `need_index_for()` says
  to.
- `unload_tapedeck()` specifically — regression test for the
  documented pre-refactor `AttributeError` (missing `reindex` kwarg on
  the unload path) to make sure it doesn't come back.

---

## 6. `core/`

### `core/download_songs.py`
- `_resolve_source()` — existing file/dir passthrough vs. bare Spotify
  URL written to a temp one-line `.txt`.
- Dry-run behavior — **each step actually runs in its own no-op mode**
  (`validate_only=True`, `dry_run=True`, `apply=False`), not skipped
  entirely. This is called out as a deliberate behavior change from the
  old subprocess pipeline, so it's worth a test that would catch a
  regression back to "dry run does nothing."
- `--only` — repeatable flag runs the specified steps in fixed order
  regardless of the order given on the command line.
- Return shape — `{'steps': [...], 'ok': bool}` with correct
  `ok`/`error`/`skipped` per step on both a success and an injected
  failure.

### `core/sync.py`
- `run_sync()` — thin wrapper correctly forwards to
  `build_playlists()`; no dry-run mode of its own (calling
  `build_playlists(apply=False, ...)` directly is the documented way to
  preview — test that this actually works as an equivalent, not just
  that it's documented as the way).

---

## Appendix: fixture data needed

Building the above will need, at minimum:
- A handful of tagged audio fixture files (small/silent, just needs
  valid tags) covering: a clean album, a per-track-artist-split album
  (for `organize.cleanup`'s repair-mode tests), a loose singleton, and
  an all-symbol-title track (for matcher tier 6).
- A small fixture `spotify_manifest.csv` / `playlists_manifest.csv` with
  real column headers (**pull one real header row from an actual
  export** rather than guessing — this directly resolves the
  `album`/`album_name` uncertainty in `download.manifest`).
- A fixture `playlists.csv` with an `owner` display-name column, for the
  known `playlists/build.py` bug test.
- Canned spotdl stdout snippets containing each soft/hard failure
  marker string, for `spotify_download.py`'s classification tests.
- A fixture `failed_downloads.txt`/`soft_failures.txt` pair with an
  overlapping URL logged under different reasons in each, for
  `retry.py`'s union/dedup tests.
