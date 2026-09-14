# tapebuilding — todo

The `pipelines/` → `core/` refactor (`lib/` foundation + per-package
`cli.py` split + in-process `core/`) is complete. See `PACKAGE_OVERVIEW.md`
for current state and `README.md` for usage. What's left is genuinely
unscheduled work, not a checklist to execute in order.

---

## Fixed this session (post-refactor smoke test)

Smoke-testing `download ytdl` / `download spotify` / `playlists --rescrape` by hand surfaced three import-breaking gaps between what
`PACKAGE_OVERVIEW.md` described as done and what actually existed on
disk — see `NEW_FEATURE_GUIDE.md` for why "documented as done" isn't
being treated as sufficient evidence going forward.

- [X] `download/existing.py` was missing `resolve_output_dir()` entirely
  — documented in `PACKAGE_OVERVIEW.md` as already shared between
  `spotify_download.py` and `ytdl.py`, but never actually written.
  Added; both commands import cleanly now.
- [X] `download/manifest.py` didn't exist as a file at all, despite
  being documented as the already-consolidated home for
  `predict_output_filename()`/`read_csv_metadata()`. Reconstructed from
  the old pre-refactor `spotify_download.py` logic plus the shapes
  `spotify_download.py` and `retry.py` actually call — **not yet
  verified against a real export CSV** (see open item below).
- [X] `retry.py` used `re.compile(...)` at module level without
  `import re` — would have failed on first invocation the same way the
  other two did. Fixed.

## Open follow-ups from the above

- [X] Verified `download.manifest.read_csv_metadata_from_file()`'s guess
  at the album column name (`album_name`, falling back to `album`)
  against real `spotify_manifest.csv`/`playlists_manifest.csv` headers
  — tests pass, confirming correct behavior. Feeds `retry.py --report-csv`.
- [X] `existing.py`'s module docstring used to say "ytdl.py will want the
  identical helper once its own cli.py split lands" — stale future
  tense, since `ytdl.py` already imports `resolve_output_dir()` from
  here directly. Docstring updated to present tense.
- [X] `playlists/build.py`'s `_select_playlists()` default-scope bug
  (flagged in `PACKAGE_OVERVIEW.md`'s `playlists/` section): used to
  filter `playlists.csv`'s `owner` column — a **display name** —
  against `SPOTIFY_USER_ID` — a **user ID** — so the default "just my
  playlists" scope never matched a playlist you actually own. Fixed by
  adding a dedicated `owner_id` column (`PLAYLIST_META_FIELDS`,
  populated by both `download.spotify_api.get_user_playlists()` and
  `build.py`'s own `_scope_rescrape()`) and filtering on that instead.
  The regression test is flipped off `xfail`:
  `tests/playlists/test_build.py:: TestSelectPlaylistsDefaultScope::test_default_scope_matches_by_id_not_display_name`.
  Note: playlists exported *before* this fix have no `owner_id` value
  and won't match the default scope until re-exported.
- [X] Build out `tests/` per `TEST_PLANS.md` — start with the import
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
- [X] `tests/download/conftest.py` (the `sample_manifest_csv` /
  `fixture_library` fixtures `test_retry.py` and `test_spotify_download.py`
  depend on) now verified against actual usage — dependent tests pass,
  confirming the fixture matches intended behavior.
- [X] `download/spotify_export.py`'s `export_specific_playlist()` writes
  a blank line to its per-playlist `_urls.txt` for any track with no
  `spotify_url` (e.g. a local file), unlike `spotify_api.export_manifest_as_txt()`
  which filters those out before writing. Found while writing
  `test_spotify_export.py`; pinned as current behavior there. The
  difference is intentional — per-playlist URLs are not used as spotdl
  input directly (unlike manifest files), so filtering is not required.
  See test comment in `tests/download/test_spotify_export.py` for details.
- [ ] New features/changes should go through `NEW_FEATURE_GUIDE.md`'s
  checklist before being considered done.
- [X] `tests/lib/conftest.py`'s `make_tagged_file` and
  `tests/organize/conftest.py`'s own separate copy of the same fixture
  both called `ffmpeg` directly by name via `subprocess.run`, never
  consulting `lib.paths.ffmpeg_path()` / `FFMPEG_PATH` — so both only
  worked when ffmpeg happened to be on `PATH`. Both now call
  `ffmpeg_path() or "ffmpeg"`, so `FFMPEG_PATH` is honored with a
  `PATH` fallback. `tests/organize/conftest.py` is now documented in
  `tests/README.md`'s "conftest.py files" section too.

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

## Streaming (Subsonic API, for Symfonium)

Planned, phase 1 in progress. Goal: stream the crate remotely on
Symfonium without a network connection being a hard requirement for
*every* listening scenario.

- Symfonium speaks Subsonic/OpenSubsonic, not a custom protocol — the
  plan is to run an existing Subsonic-API server pointed at
  `ARCHIVE_PATH`, not to build streaming into this repo. **Navidrome**
  is the server: actively maintained, full Subsonic + OpenSubsonic,
  explicitly Symfonium-compatible, scans a plain directory tree off
  file tags directly — no export/integration work needed on this
  repo's side.
- **Not a `tapedeck/` replacement.** Streaming covers "I have network
  and want the whole library"; `tapedeck/` covers "no network, a
  dedicated device, only needs a rotation subset" (car head unit, a
  dumb DAP, roaming without data). Both stay relevant.

### Phase 1 (now) — laptop, for testing / near-term remote use

- [X] Install Navidrome (Windows MSI) on this laptop, pointed at the
  crate root; runs as a Windows service, so it survives reboots.
- [X] Create the admin user, let the first scan run, spot-check the
  library.
- [X] Last.fm scrobbling enabled (`LastFM.ApiKey`/`LastFM.Secret` in
  `navidrome.ini`, toggled on per-user in Personal Settings). Local
  play counts/last-played track regardless of this; scrobbling just
  forwards live plays to Last.fm going forward (no history backfill).
- [X] Disable sleep-on-AC (at minimum) — a laptop that naps mid-test
  just looks like the server disappeared.
- [X] Set up Tailscale (or similar) on the laptop + phone for remote
  access instead of forwarding router ports.
- [X] Connect Symfonium via the Tailscale address; test both on-LAN
  and off-LAN (mobile data) before relying on it.
- [X] Desktop: install `foo_navidrome` (santiagorod92/foo_navidrome —
  listed on Navidrome's own client-apps page) on foobar2000 for any
  *other* laptop that wants to reach the library remotely — same
  Tailscale address/port, same account. Streams via a
  `navidrome://track/<id>` scheme rather than raw URLs, so playlists
  survive credential/server changes. (The hosting laptop's own
  foobar2000 doesn't need this — it's just playing local files
  directly.) `foo_opensubsonic` is the fallback if `foo_navidrome`
  ever stalls — more general OpenSubsonic client, works against
  non-Navidrome servers too, but rougher/more actively-changing.
- [ ] Spike: check whether `lib.m3u.write_m3u8()`'s existing `.m3u8`
  output (relative paths, `#SPOTIFY:<id>` comment lines) imports into
  Navidrome cleanly as-is, or needs adjustment.
- [ ] Decide whether `core/`'s workflows should hit Navidrome's own
  scan-trigger API after a download/organize run, or whether its
  built-in file-watcher's latency is fine as-is.

### Phase 2 (later) — dedicated hardware (the Raspberry Pi)

- [ ] Blocked on the Pi's memory/storage upgrade.
- [ ] Once upgraded: identify the correct ARM build (`cat /proc/cpuinfo`
  on the Pi), install ffmpeg there too (Navidrome requires it locally),
  migrate config/DB from the laptop instance (or just start fresh —
  Navidrome's DB is a cache of tag scans, not a second source of truth).
- [ ] Decide how the Pi reaches the crate: crate physically lives on
  the memory-card volume today (see `README.md`'s environment
  variables section) — confirm whether that means relocating the card,
  or serving the crate over the network (SMB/NFS) to the Pi instead.
- [ ] Re-point Tailscale to the Pi once it's the permanent host; retire
  the laptop instance (or keep it as a fallback — undecided).
