# tapebuilding — todo

The `pipelines/` → `core/` refactor (`lib/` foundation + per-package
`cli.py` split + in-process `core/`) is complete. See `PACKAGE_OVERVIEW.md`
for current state and `README.md` for usage. What's left is genuinely
unscheduled work, not a checklist to execute in order.

---

## Fixed this session (post-refactor smoke test)

Smoke-testing `download ytdl` / `download spotify` / `playlists
--rescrape` by hand surfaced three import-breaking gaps between what
`PACKAGE_OVERVIEW.md` described as done and what actually existed on
disk — see `NEW_FEATURE_GUIDE.md` for why "documented as done" isn't
being treated as sufficient evidence going forward.

- [x] `download/existing.py` was missing `resolve_output_dir()` entirely
  — documented in `PACKAGE_OVERVIEW.md` as already shared between
  `spotify_download.py` and `ytdl.py`, but never actually written.
  Added; both commands import cleanly now.
- [x] `download/manifest.py` didn't exist as a file at all, despite
  being documented as the already-consolidated home for
  `predict_output_filename()`/`read_csv_metadata()`. Reconstructed from
  the old pre-refactor `spotify_download.py` logic plus the shapes
  `spotify_download.py` and `retry.py` actually call — **not yet
  verified against a real export CSV** (see open item below).
- [x] `retry.py` used `re.compile(...)` at module level without
  `import re` — would have failed on first invocation the same way the
  other two did. Fixed.

## Open follow-ups from the above

- [x] Verified `download.manifest.read_csv_metadata_from_file()`'s guess
  at the album column name (`album_name`, falling back to `album`)
  against real `spotify_manifest.csv`/`playlists_manifest.csv` headers
  — tests pass, confirming correct behavior. Feeds `retry.py --report-csv`.
- [ ] `existing.py`'s module docstring still says "ytdl.py will want the
  identical helper once its own cli.py split lands" — stale future
  tense now that it's actually implemented; cosmetic cleanup.
- [x] `playlists/build.py`'s `_select_playlists()` default-scope bug
  (flagged in `PACKAGE_OVERVIEW.md`'s `playlists/` section): used to
  filter `playlists.csv`'s `owner` column — a **display name** —
  against `SPOTIFY_USER_ID` — a **user ID** — so the default "just my
  playlists" scope never matched a playlist you actually own. Fixed by
  adding a dedicated `owner_id` column (`PLAYLIST_META_FIELDS`,
  populated by both `download.spotify_api.get_user_playlists()` and
  `build.py`'s own `_scope_rescrape()`) and filtering on that instead.
  The regression test is flipped off `xfail`:
  `tests/playlists/test_build.py::
  TestSelectPlaylistsDefaultScope::test_default_scope_matches_by_id_not_display_name`.
  Note: playlists exported *before* this fix have no `owner_id` value
  and won't match the default scope until re-exported.
- [x] Build out `tests/` per `TEST_PLANS.md` — start with the import
  smoke tests (§0), since all three bugs fixed above were import-time
  failures that a two-line test per module would have caught before
  any manual `uv run` was needed. `lib/` (§1), `download/` (§2),
  `organize/` (§3), `playlists/` (§4), and now `tapedeck/` (§5) are all
  fully real (or, for `playlists/`, real-plus-one-known-`xfail`) — no
  skeletons left in any of the five. `core/` (§6) is the only package
  left per the priority order.
  - `tapedeck/`'s tests turned up one genuine quirk in `copy.py`'s
    `unstage()`, not a bug: its empty-directory pruning is a single
    bottom-up `os.walk`, so a parent directory that only becomes empty
    *because* its own child was just removed in the same pass isn't
    re-checked and survives until a later unload's prune pass. Pinned as
    current behavior in `test_unstage_prunes_empty_parent_directories`
    rather than fixed — worth deciding whether it's worth a follow-up
    fix (e.g. two pruning passes, or a fixed-point loop) or is fine as
    documented behavior.
- [x] `tests/download/conftest.py` (the `sample_manifest_csv` /
  `fixture_library` fixtures `test_retry.py` and `test_spotify_download.py`
  depend on) now verified against actual usage — dependent tests pass,
  confirming the fixture matches intended behavior.
- [x] `download/spotify_export.py`'s `export_specific_playlist()` writes
  a blank line to its per-playlist `_urls.txt` for any track with no
  `spotify_url` (e.g. a local file), unlike `spotify_api.export_manifest_as_txt()`
  which filters those out before writing. Found while writing
  `test_spotify_export.py`; pinned as current behavior there. The
  difference is intentional — per-playlist URLs are not used as spotdl
  input directly (unlike manifest files), so filtering is not required.
  See test comment in `tests/download/test_spotify_export.py` for details.
- [ ] New features/changes should go through `NEW_FEATURE_GUIDE.md`'s
  checklist before being considered done.
- [ ] `tests/lib/conftest.py`'s `make_tagged_file` and
  `tests/organize/conftest.py`'s own separate copy of the same fixture
  both call `ffmpeg` directly by name via `subprocess.run`, never
  consulting `lib.paths.ffmpeg_path()` / `FFMPEG_PATH` — so both only
  work when ffmpeg happens to be on `PATH`. Neither fixture currently
  fails loudly about this (just a bare `WinError 2` / `FileNotFoundError`
  on Windows), and `tests/organize/conftest.py` isn't mentioned in
  `tests/README.md`'s "conftest.py files" section at all. Worth either
  routing both through `ffmpeg_path()` with a `PATH` fallback, or at
  least documenting the `PATH` requirement clearly in both places.

---

## Enhancements

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

## `app/`

Not started. See `WEB_APP_PLAN.md` for the constraints and shape already
agreed on (no subprocess/CLI dependency from below; progress-reporting
mechanism still an open question).
