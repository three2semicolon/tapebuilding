# tapebuilding - todo

## Next steps

---

## Enhancements

- [X] spotdl fallback, option to turn on so that each song/album that cant be found (spotdl) asks user to input either the youtube music or path to existing file so it can be matched in the future (implemented via download.fallback module)
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
