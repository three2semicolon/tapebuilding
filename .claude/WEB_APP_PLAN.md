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
