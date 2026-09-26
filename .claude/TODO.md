# tapebuilding — todo

The `pipelines/` → `core/` refactor (`lib/` foundation + per-package
`cli.py` split + in-process `core/`) is complete. See `PACKAGE_OVERVIEW.md`
for current state and `README.md` for usage. What's left is genuinely
unscheduled work, not a checklist to execute in order.

---

## Fixes — planned (found this planning session, not yet implemented)

Two matching/organization bugs surfaced from real playlist syncs, plus
one enhancement they motivate. Full root-cause analysis and fix plan in
`BUGFIX_PLAN.md` (new) — the summary below isn't enough to implement
from directly; that file lists the exact source files and a verification
script needed to confirm each hypothesis before touching code.

- [X] **Multi-artist tracks land in `unmatched.csv` despite already
  being in the crate**, then get reimported into beets' duplicates
  folder. **Root cause confirmed, fix implemented and tested.**
  `lib.text.split_artists()` was never the problem (third revision, not
  the original separator hypothesis). The real bug was
  `lib.catalog.indexer.get_index()` trusting `.playlist_index.jsonl`
  unconditionally — confirmed by running `playlists --apply --rescrape
  --reindex`, which recovered "I Admit with Isaiah Kaleo" plus ~300
  other tracks that had silently accumulated across un-reindexed
  `download spotify` sessions. `get_index()` now does a cheap stat-only
  mtime check (`_is_stale()`) before trusting the cache, and rebuilds
  automatically when the crate has changed — tested against add/
  no-change/delete cases with stub modules, all three behave correctly.
  `--reindex` still works as a manual override. Full detail in
  `BUGFIX_PLAN.md` §Bug 1.
  - [X] Regression test added:
    `tests/lib/catalog/test_indexer.py` now covers the add/delete/
    unchanged-crate cases against the real fixed `get_index()`, plus a
    direct assertion that `build_index()` is/isn't actually called
    (not just that the output happens to look right). One pre-existing
    test in that file had been asserting the old buggy behavior as
    correct (`len(index) == 1` after adding a file) — fixed to assert
    the corrected behavior, with a docstring note on why.
  - [X] `PACKAGE_OVERVIEW.md`'s `lib/catalog/indexer.py` description
    updated to describe `_is_stale()`/`_newest_mtime()` auto-invalidation,
    the fail-safe direction in each case, and the Bug 1 fix it closes,
    per `NEW_FEATURE_GUIDE.md` §5.4.
- [X] **Unrelated same-titled singles by different artists merged into
  one album folder** (e.g. two different artists' singles both titled
  "Automatic" ending up in one `Automatic/` folder) — **fixed and
  smoke-tested**. `organize.cleanup.group_files()` still buckets by
  album title first, but `build_plan()` (both `cleanup.py`'s and
  `preimport.py`'s) now calls the new `is_unrelated_va_collision()`
  right after `canonical_albumartist()` resolves a group: an exactly-
  two-track group that only came out `'Various Artists'` because the
  two members share zero artist tokens, and neither file's own
  `albumartist` tag actually says VA, gets filed as two singletons
  instead of merged. Verified against a standalone stub-module script
  (same pattern `BUGFIX_PLAN.md`'s Bug 1 fix used) with three cases: the
  real `Anysia Kym`/`Spencer.` "Automatic" collision (now splits), a
  genuine shared-artist-token album (still merges), and an explicitly
  VA-tagged compilation (still merges) — all three pass. See
  `BUGFIX_PLAN.md` §Bug 2.
  - [ ] Regression test still owed: the standalone script above needs
    turning into a real `tests/organize/test_cleanup.py` /
    `test_preimport.py` case per `NEW_FEATURE_GUIDE.md` §5.2/5.3 — same
    "still needs wiring into the actual suite" gap Bug 1's fix had
    before it was closed out.
  - [ ] `organize cleanup`'s resplit mode (see the item below) is still
    needed to fix folders that were already wrongly merged *before*
    this fix landed — this only stops *new* bad merges.
- [ ] **`organize cleanup` needs a resplit mode** to repair
  already-wrongly-merged folders once the grouping-key fix above lands
  — **implemented and smoke-tested as `plan_resplit()`/`run_resplit()`
  in `cleanup.py`**, opt-in and separate from the regular `--apply`
  pass (a normal `cleanup --apply` run can't undo the historical damage
  on its own: an already-wrongly-merged folder now carries a
  self-inflicted `'Various Artists'` albumartist tag that looks like a
  genuine compilation signal to the forward-looking check, so resplit
  recomputes each folder's grouping from the untouched raw `artist` tag
  instead). Dry-run by default, `--apply` to actually move files,
  matching every other command's convention; doesn't rebuild `beets.db`
  or the crate catalog itself, prints a reminder to run
  `cleanup --rebuild-db` + a playlists/tapedeck reindex afterward.
  Verified against a real (temp-dir) filesystem: a poisoned
  `Various Artists - Automatic` folder splits into two singles and the
  old folder is removed; a genuine multi-track album with chained
  artist overlap (varying featured collaborators per track, like the
  real Ash Levi album) is correctly left untouched.
  - [ ] **Blocked on `organize/cli.py`**: `run_resplit()` isn't wired to
    a `--resplit` flag yet — that file hasn't been shared in this
    thread, so the CLI-argument-parsing side of this is still open.
    Upload it to close this out, then update `README.md`'s `organize`
    usage section per `NEW_FEATURE_GUIDE.md` §5.5 (new user-facing
    flag needs both docs updated, not just `PACKAGE_OVERVIEW.md`).
  - [ ] Regression test still owed (same gap as Bug 2's grouping-key
    fix above) — the filesystem smoke test used to verify this should
    become a real `tests/organize/test_cleanup.py` case.

---

## Resolved (historical)

Compressed from an earlier session's full log — the detail (which files,
which tests, which exact lines) isn't load-bearing anymore now that
`PACKAGE_OVERVIEW.md` describes the current state directly; kept here
only so the "documented as done ≠ actually done" lesson stays visible.

- [X] Post-refactor smoke testing found and fixed three import-breaking
  gaps `PACKAGE_OVERVIEW.md` had described as already done:
  `download.existing.resolve_output_dir()` missing entirely,
  `download/manifest.py` missing as a file, and `retry.py` missing
  `import re`. Motivated `NEW_FEATURE_GUIDE.md`'s "actually run it"
  checklist.
- [X] Verified `download.manifest`'s album-column guess, the
  `existing.py` docstring, `spotify_export.py`'s blank-line-on-no-url
  behavior (pinned intentional), and the `conftest.py` fixtures against
  real usage/exports.
- [X] Fixed `playlists/build.py`'s default-scope bug — was filtering
  `playlists.csv`'s `owner` (display name) against `SPOTIFY_USER_ID`
  (user ID), so the default "just my playlists" scope never matched.
  Now uses a dedicated `owner_id` column. Playlists exported *before*
  this fix need re-exporting to pick up `owner_id`.
- [X] Built out `tests/` through `lib/`, `download/`, `organize/`,
  `playlists/`, `tapedeck/` (§0–§5 of `TEST_PLANS.md`). `core/` (§6) is
  the only package still pending.
- [X] Fixed a stray lowercase-`ffmpeg_path` env-var fallback in two test
  fixtures that bypassed `lib.paths.ffmpeg_path()`.

---

## Enhancements

- [ ] SoundCloud export/download + a `--exclude` flag for Spotify
  playlist sync + the cross-service playlist design both feed into —
  full plan in `PLAYLIST_SYNC_PLAN.md` (new), superseding the shorter
  note this bullet used to be. Short version:
  - `download soundcloud` (new subcommand, mirroring `download
    export`/`download spotify`'s split) lands in `download/`, not a new
    top-level package, via `yt-dlp extract_flat` — same reasoning as
    before, still just leaning that way rather than deciding it forever.
  - `--exclude NAME_OR_ID` (repeatable) on `playlists/build.py`'s
    `_select_playlists()`, so specific playlists (soundtrack/personal
    ones you don't want synced) can be skipped from `--apply
    --rescrape`/`core sync` without needing `-p` to enumerate everything
    else by hand.
  - Longer-term: a `core`-level workflow that chains rescrape → match →
    autodownload-unmatched → rematch for either service, which is what
    the eventual web app's downloader/sync pages actually want
    underneath them. See `PLAYLIST_SYNC_PLAN.md` §3 for why this should
    wait until the exclude flag and the SoundCloud manifest both exist.
- [ ] `core/` (§6 of `TEST_PLANS.md`) is the only package without a real
  test suite yet — the other five are done.
- [ ] `tapedeck/copy.py`'s `unstage()` prunes empty directories with a
  single bottom-up `os.walk`, so a parent directory that only becomes
  empty *because* its own child was just removed in the same pass isn't
  re-checked, and survives until a later unload's prune pass. Pinned as
  current behavior in a test, not fixed — decide whether it's worth a
  follow-up (two pruning passes, or a fixed-point loop) or is fine as
  documented behavior.

## `app/`

Not started. See `WEB_APP_PLAN.md` for the constraints and shape already
agreed on (no subprocess/CLI dependency from below), plus its new
"Feature-set decision" and "Progress reporting" sections — the feature
list is now scoped down against what Navidrome's own web app already
covers, and progress-reporting has a concrete recommendation instead of
being fully open.

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
- [X] Spike: check whether `lib.m3u.write_m3u8()`'s existing `.m3u8`
  output (relative paths, `#SPOTIFY:<id>` comment lines) imports into
  Navidrome cleanly as-is, or needs adjustment.
- [X] Investigated Symfonium's mobile playlist management (the "doesn't
  seem I can add or manage Navidrome playlists from there" gap) — it
  does support creating/editing/pushing playlists to Navidrome, but each
  server-side playlist needs an explicit one-time **Import** before
  Symfonium will edit + sync it, and sync itself is one-directional per
  action (full upload or full download, not a merge). See
  `WEB_APP_PLAN.md`'s new Symfonium section. Try the import step before
  defaulting to `tapedeck` for heavily-edited playlists.
- [ ] Decide whether `core/`'s workflows should hit Navidrome's own
  scan-trigger API after a download/organize run, or whether its
  built-in file-watcher's latency is fine as-is.
  - [ ] built in is enough

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