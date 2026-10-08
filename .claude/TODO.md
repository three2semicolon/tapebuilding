# tapebuilding - todo

## Next steps

---

## Enhancements

- [X] spotdl fallback, option to turn on so that each song/album that cant be found (spotdl) asks user to input either the youtube music or path to existing file so it can be matched in the future (implemented via download.fallback module)
- [X] SoundCloud export/download + a `--exclude` flag for Spotify
  playlist sync + the cross-service playlist design both feed into —
  full plan in `PLAYLIST_SYNC_PLAN.md` (new), superseding the shorter
  note this bullet used to be. Short version:
  - `download soundcloud` (new subcommand, mirroring `download export`/`download spotify`'s split) lands in `download/`, not a new
    top-level package, via `yt-dlp extract_flat` — same reasoning as
    before, still just leaning that way rather than deciding it forever.
  - `--exclude NAME_OR_ID` (repeatable) on `playlists/build.py`'s
    `_select_playlists()`, so specific playlists (soundtrack/personal
    ones you don't want synced) can be skipped from `--apply --rescrape`/`core sync` without needing `-p` to enumerate everything
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

---

## Feature-set decision (planning session update)

Navidrome's own web app already covers browse/search/play well — that's
not something `app/` needs to duplicate. Scoping `app/` to what Navidrome
*doesn't* do:

1. **Playlist management** — create/rename/delete, move tracks between
   playlists, reorder. Covers both Spotify-sourced local `.m3u8`s and
   (once built, see `PLAYLIST_SYNC_PLAN.md`) SoundCloud ones.
   - **Design question this raises:** does `app/` manage the local
     `.m3u8` files that feed Navidrome's own scan (so a change here needs
     Navidrome to notice — the same scan-trigger-vs-file-watcher
     question `TODO.md`'s Phase 1 already flagged), or does it read/write
     Navidrome's own playlist records directly via the Subsonic API?
     These are two different implementations with different sources of
     truth. **Recommend the former** — keep the `.m3u8` + crate + matcher
     model this repo already has as the one source of truth, and let
     Navidrome just scan the result, rather than introducing a second
     playlist store that can drift out of sync with it.
2. **Downloader page** — paste a Spotify/SoundCloud track/playlist/album
   URL, it runs the equivalent of `download spotify`/`download soundcloud`/`download ytdl` under the hood, shows live progress, drops
   the result into the crate. This is the strongest case for actually
   deciding the progress-reporting question now (see below) — a
   multi-minute download run has no synchronous-request-friendly shape.
3. **Command runway** — `core sync`, `organize cleanup` (and, once built,
   `organize cleanup --resplit` — see `BUGFIX_PLAN.md`), per-service
   playlist refresh, run from a jobs page. Recommend a plain "run this
   job, show me the log tail + final ok/fail" surface rather than a
   bespoke UI per command, at least for a first pass.

None of the above is something Navidrome's web UI + Subsonic API gives
you for free — it doesn't run arbitrary local Python or trigger
downloads — so building `app/` for this is still worth it.

## Progress reporting — recommendation

Previously left fully open (see "Not yet decided" above); the downloader
page above makes this concrete enough to actually propose something
rather than leave it open indefinitely.

- **Job store:** a small in-process module (e.g. `core/jobs.py` or
  `app/jobs.py` — either works, since `app/` can import `core/` directly
  per the constraints above) wrapping a background thread per job,
  storing `{'id', 'state': running|ok|error, 'log': [...], 'result': ...}` in memory (or a tiny sqlite/json file if `app/` needs jobs to
  survive its own process restarting).
- **Bridging the print()-narration problem:** most domain functions
  narrate progress via bare `print()` today. Two ways to surface that
  without rewriting every domain function:
  - **(a)** redirect stdout during the job's thread and append each line
    to the job's log — zero changes to domain code, but no structure
    (can't tell "%-done" from a plain log line).
  - **(b)** thread an optional `on_progress(event: dict)` callback
    through the handful of functions that already return structured
    per-step data (`run_download_songs()`'s `steps` list,
    `download_spotify()`'s per-batch loop, `run_retry()`'s counts), so
    the job store gets real structured events where they're cheap to
    add, falling back to (a) everywhere else.
  - **Recommend starting with (a) everywhere** (fastest, no domain-code
    changes), layering **(b)** in only for `download_spotify()`'s
    (and, once built, `download_soundcloud()`'s) per-track loop
    specifically — that's the one place "still running…" is a
    noticeably worse UX than "3/47 tracks."
- **Frontend:** poll `/jobs/<id>` on an interval. Simplest option, no
  websockets needed for a single-user LAN/Tailscale app. Revisit
  SSE/websockets only if polling feels laggy in practice — don't build
  that up front on spec.

## Symfonium mobile playlist management — investigated

Checked current state rather than going on the "doesn't seem I can
add/manage playlists from there" impression: Symfonium **can** create,
edit, and push/sync playlists to Navidrome — it's supported, not missing
— but two things likely explain why it looked broken:

1. **Import isn't automatic.** A playlist created in Navidrome doesn't
   just show up editable in Symfonium — each one needs an explicit
   one-time **Import** action before Symfonium will let you edit it and
   push changes back. Users hitting this exact confusion is a recurring
   thread on Symfonium's own support forum.
2. **Sync is one-directional per action, not a merge.** "Push to server"
   fully overwrites the server copy with your local one; "pull from
   server" does the reverse. Editing the same playlist from two
   devices/apps between syncs can silently clobber changes rather than
   merging them — worth knowing before leaning on it as your only edit
   path.

**Recommendation:** try the explicit per-playlist Import step before
falling back to `tapedeck` for playlists you expect to edit a lot — keep
`tapedeck` as the fallback specifically for playlists you don't want
round-tripping through that one-directional sync model at all, which is
what `TODO.md` already anticipated ("worst case I'll just use the
tapedeck to load certain playlists").

Source: [Symfonium support forum, &#34;Playlist
Support Question&#34;](https://support.symfonium.app/t/playlist-support-question/7626).

## SoundCloud Export Improvements (Completed)

- [X] Added `export_likes` function to export SoundCloud likes to CSV/TXT files
- [X] Updated `export_all_data` function to properly export all sets and optionally likes
- [X] Updated `export_specific_set` and `export_sets` functions to use service-specific subdirectories
- [X] Simplified CLI soundcloud export command to delegate to module functions

## Spotify Export Improvements (Completed)

- [X] Updated `export_specific_playlist`, `export_playlists`, and `export_all_data` functions to use service-specific subdirectories
- [X] All spotify export functions now write to `export_dir/spotify/` instead of `export_dir/`

## Export Organization (Completed)

- [X] SoundCloud exports now organized in `export_dir/soundcloud/`
- [X] Spotify exports now organized in `export_dir/spotify/`
- [X] Consistent service-specific organization throughout the project

## Remaining Items

- [ ] Investigate matching/unmatched track issues (user reported comparing uploader username rather than artist name)
- [ ] Verify bitrate parameter error resolution (could not reproduce error in current code)
- [X] Consider if `_process_soundcloud_crate_check` should be moved to a more appropriate location
  - [X] removed crate checking from download cli
