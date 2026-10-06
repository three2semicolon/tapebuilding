# tapebuilding — web app plan

see `PACKAGE_OVERVIEW.md` for the current state).
`app/` itself hasn't been started — this
is the shape it's meant to take once picked up.

## What `app/` is

A thin layer on top of everything else in the repo:

- imports `lib/`, the domain packages (`download/`, `organize/`,
  `playlists/`, `tapedeck/`), and `core/` directly — no subprocess, no
  shelling out to CLIs it doesn't own,
- runs locally as a browser app for manipulating the library,
- potentially streams the library out to Symfonium on a phone.

## Constraints already agreed on

- **Nothing below `app/` should assume a terminal or a CLI invocation is
  the only way in.** This is already true today: every domain package's
  core functions are plain, import-safe functions that don't call
  `sys.exit()` or print `--help` — `cli.py` is the only thing in each
  package that knows it's being run from a terminal. `core/` was built the
  same way (`run_download_songs()`/`run_sync()` return structured results;
  `core/cli.py` is the only place that turns those into exit codes).
- **`app/` isn't forced through `core/` for everything.** It may call a
  single domain package function directly for a one-step action, or a
  `core/` function for a multi-step preset — same relationship `core/`
  already has with the domain packages.
- **No architecture decisions for `app/` are being made yet** beyond the
  above. In particular:
  - **Progress reporting is still an open question.** Domain functions
    mostly report progress via `print()` today (some, like
    `download.spotify_download.download_spotify()`, print their own
    progress **and** return a bool; others print internally without a
    structured return at all). A browser app can't "watch a terminal," so
    `app/` will need *some* other channel — logging module, callback,
    polling a job-status store — but which one is a real design decision
    to make when `app/` work actually starts, not something to guess at
    now.
  - Whether `app/` talks to the domain packages synchronously (a request
    blocks until the operation finishes) or needs a job queue / background
    worker for long-running operations (a full library download, a
    crate-wide cleanup) is also undecided.

## What's already in place to build on

- **Structured return values** exist where they matter most for a UI:
  `core.download_songs.run_download_songs()` returns
  `{'steps': [{'step', 'ok', 'error', 'skipped'}, ...], 'ok': bool}`;
  `organize.preimport.stage()` and `organize.beets_import.run_import()`
  return/consume report dicts; `download.retry.run_retry()` and
  `download.soundbyte.run_soundbyte()` return full breakdown dicts rather
  than relying on print output.
- **No dependency on a step being separately invocable via `python -m`** —
  everything is a plain importable function now, so `app/` (or `core/`)
  can call a step twice, partially, or with in-memory data instead of a
  file on disk, without shelling out.
- **One shared foundation (`lib/`)** for path resolution, tag reading,
  matching, and auth — `app/` doesn't need to reinvent or duplicate any of
  that; it's exactly the same surface the CLIs use.

## Not yet decided / explicitly deferred

- Web framework / frontend approach.
- Auth story for the browser app itself (as opposed to the Spotify OAuth
  `lib.spotify_auth` already handles).
- Whether streaming to Symfonium is a first pass feature or a later
  addition once the local browser app itself works.
- The progress-reporting mechanism (see above).

None of this needs solving now — flagged here so it's not accidentally
foreclosed by a shortcut taken elsewhere in the codebase before `app/`
work actually begins.

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
   URL, it runs the equivalent of `download spotify`/`download
   soundcloud`/`download ytdl` under the hood, shows live progress, drops
   the result into the crate. This is the strongest case for actually
   deciding the progress-reporting question now (see below) — a
   multi-minute download run has no synchronous-request-friendly shape.
3. **Command runway** — `core sync`, `organize cleanup` (see `BUGFIX_PLAN.md`
   for details on the retirement of `--resplit`), per-service
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
  storing `{'id', 'state': running|ok|error, 'log': [...], 'result':
  ...}` in memory (or a tiny sqlite/json file if `app/` needs jobs to
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

Source: [Symfonium support forum, "Playlist Support
Question"](https://support.symfonium.app/t/playlist-support-question/7626).
