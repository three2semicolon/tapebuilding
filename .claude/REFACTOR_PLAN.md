# tapebuilding — refactor plan

Companion to `PACKAGE_OVERVIEW.md` (what exists today) and `TODO.md` (the
checklist to execute this plan). This document is the *why* and *what the end
state looks like* — the todo list is the *in what order*.

## Goals

1. **One shared foundation (`lib/`)** that every domain package depends on,
   instead of packages reaching into each other's internals for things like
   path resolution, string normalization, and tag reading.
2. **Every package gets a `cli.py`** that's just argument parsing + calling a
   real function + printing/exiting. All actual logic lives in plain
   functions that don't know they're being run from a terminal.
3. **`pipelines/` becomes `core/`**, and stops shelling out via subprocess —
   it calls the domain packages' functions directly, in-process.
4. **`app/`, later**, sits on top of `lib/` + the domain packages + `core/`,
   for a local browser app and (eventually) remote streaming.
5. Delete `tapebuilding/` (the legacy combined package) entirely.
6. Kill accidental inconsistency along the way — dual-case env vars, four
   copies of the same normalize function, copy-pasted helpers — without
   inventing new abstraction for its own sake. Prefer several small, clean
   files over one large one.

## Target tree

```
src/
  lib/
    __init__.py
    paths.py            # all root/dir resolution, one convention
    text.py              # normalize_key(), normalize_title()
    tags.py               # EXTENSIONS, sanitize(), read_tags(), write_tag(),
                           #   canonical_albumartist(), dominant_album(),
                           #   scan_audio(), safe_move()
    m3u.py                 # write_m3u8(), read_m3u8() (paths + track ids + EXTINF)
    spotify_auth.py         # authenticate_user(), authenticate_client()
    catalog/
      __init__.py
      indexer.py            # crate-wide tag index + jsonl cache
      matcher.py            # tiered spotify-row -> local-file matching

  download/
    __init__.py
    cli.py
    spotify_export.py       # was spotify_to_csv.py
    spotify_download.py     # was download_spotify.py
    ytdl.py                  # was yt_dlp_downloader.py
    retry.py                  # was retry_failures.py — rebuilt from README
    soundbyte.py               # was soundbyte_albums.py

  organize/
    __init__.py
    cli.py
    cleanup.py                # policy only now (toolkit moved to lib/tags.py)
    preimport.py
    beets_import.py
    normalize_artists.py        # beets plugin, untouched
    config.yaml
    config.yaml.example

  playlists/
    __init__.py
    cli.py
    build.py                    # indexer/matcher/m3u now come from lib/

  tapedeck/
    __init__.py
    cli.py
    resolve.py
    copy.py

  core/                          # renamed from pipelines/
    __init__.py
    cli.py                        # optional: a `core` entrypoint for presets
    download_songs.py              # was pipelines/download_songs.py, now
                                    #   calls functions in-process
    sync.py                         # the export+build+handoff flow, promoted
                                    #   from a README-documented one-liner to
                                    #   a real function
    (future preset workflows)

  app/                             # later — not part of this refactor pass
```

Every domain package's `pyproject.toml` entry point points at `cli.py:main`
(e.g. `spotify = "download.cli:spotify_main"` or similar), not at a specific
submodule's `main()` the way it does today.

## `lib/` — design per module

### `lib/paths.py`

Replaces: `organize.library`'s root resolvers, `playlists.indexer`'s root
resolvers, `tapedeck.paths`'s wrapper, and every inline
`os.getenv('ARCHIVE_PATH') or os.getenv('archive_path')` scattered around.

One general-purpose resolver, plus named convenience wrappers for the roots
that actually exist:

```python
def resolve(env_name, cli=None, default=None, required=False):
    """cli override > ENV_NAME > env_name (lowercase) > default.
    raises if required and nothing resolves."""

def archive_path(cli=None): ...       # ARCHIVE_PATH, no fallback expected in prod
def tapedeck_path(cli=None): ...      # TAPEDECK_PATH
def playlists_path(cli=None): ...     # PLAYLISTS_PATH, required=True (no fallback)
def exports_dir(playlists_path=None, cli=None): ...  # <playlists_path>/exports
```

Decide during migration whether the dual-case fallback (`ARCHIVE_PATH` /
`archive_path`) is worth preserving at all, or whether standardizing on
upper-case-only and fixing the `.env.example` is cleaner. Recommendation:
**standardize on upper-case only, update `.env.example`, drop the dual-case
fallback.** It was a documented "convention," not a requirement, and it's
pure surface area for bugs once there's one canonical resolver instead of
four independent ones to keep in sync.

### `lib/text.py`

Replaces: `organize.library._normalize`, `organize.cleanup.norm_key` (and its
dead-duplicate `norm()`), `download.spotify_utils._normalize_title` /
`_fuzzy_key`, `playlists.matcher`'s `_core_title` / `_FEAT_PAREN`.

Two tiers, matching what the four existing copies actually do between them:

```python
def normalize_key(s):
    """lowercase, strip non-alphanumeric, collapse whitespace.
    the bare normalize — used for grouping/matching keys everywhere."""

def normalize_title(s):
    """normalize_key(), but strips a leading feat./ft./featuring clause and
    parenthetical content first. used wherever a 'core' title identity
    matters more than the literal string (dedup, fuzzy matching)."""

def primary_artist(artist_string):
    """first credited artist from a 'A, B & C' / 'A feat. B' string."""

def split_artists(artist_string):
    """all credited artists from the same kind of string, as a list."""
```

`matcher.py`'s tier-4 core-title logic and `spotify_utils`'s fuzzy-key logic
both become thin callers of `normalize_title()` / `primary_artist()` instead
of maintaining their own regex.

### `lib/tags.py`

Replaces: the toolkit half of `organize.cleanup` (everything except the
regroup-in-place policy itself).

```python
EXTENSIONS = ('.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aac')

def sanitize(s): ...                 # filesystem-safe path component
def read_tags(path): ...             # -> dict: artist, albumartist, album,
                                      #    title, track, length, path
                                      #    (superset of the old tuple return —
                                      #    `length`/`path` added so indexer.py
                                      #    doesn't need its own reader)
def write_tag(path, **fields): ...   # generalizes write_albumartist()
def canonical_albumartist(files): ...
def dominant_album(files): ...
def scan_audio(root, subdirs=None): ...
def safe_move(src, dst): ...
```

`organize/cleanup.py` keeps only the regroup policy (`group_files`,
`build_plan`, `prune_empty_dirs`, `rebuild_db`, the CLI-facing `main`/`cli`
logic) and imports everything above from `lib.tags`. `organize/preimport.py`
does the same. `playlists/catalog/indexer.py` calls `lib.tags.read_tags()`
instead of its own `_read_entry()`.

### `lib/m3u.py`

Replaces: `playlists.m3u` and the parsing half of `tapedeck.resolve`
(`_parse_m3u8`) — one module, two capabilities, instead of two packages each
owning half.

```python
def write_m3u8(path, entries): ...       # was playlists/m3u.py:write_m3u8
def safe_name(name): ...
def read_m3u8(path): ...                 # -> {track_ids: [...], entries: [...]}
                                          #    replaces both parse_spotify_ids()
                                          #    and tapedeck's _parse_m3u8(),
                                          #    returning everything either
                                          #    caller needs instead of two
                                          #    separate partial readers
```

### `lib/spotify_auth.py`

Replaces: `download.spotify_utils.authenticate_spotify()` and
`download.soundbyte_albums._get_spotify_token()`.

```python
def authenticate_user():
    """OAuth user-auth flow (playlists, liked songs, follows).
    was spotify_utils.authenticate_spotify(). token cache path anchored
    properly (not a bare relative path) during migration."""

def authenticate_client():
    """client-credentials flow (public search, no login).
    was soundbyte_albums._get_spotify_token(), rewritten on spotipy
    instead of hand-rolled requests calls."""
```

### `lib/catalog/`

Promotes `playlists/indexer.py` and `playlists/matcher.py` out of
`playlists/` entirely — confirmed by the inventory that `tapedeck` already
depends on both directly, so they were never really playlists-only. This is
the "crate catalog" primitive: build/cache a searchable index of every audio
file's tags, and match an external (artist, title, album, duration) row
against it.

- `catalog/indexer.py` — unchanged in behavior, calls `lib.tags.read_tags()`
  instead of its own reader, calls `lib.paths` for root/exports resolution.
- `catalog/matcher.py` — unchanged in behavior, calls `lib.text.normalize_key`
  / `normalize_title` instead of its own regex.

`playlists/build.py` and `tapedeck/resolve.py` both import from
`lib.catalog` afterward instead of `playlists.indexer`/`playlists.matcher` —
this removes the `tapedeck → playlists` dependency entirely, leaving
`tapedeck`'s only remaining sibling dependency as whatever it needs from
`playlists.build` directly (if anything — check during migration whether it
needs any at all once catalog moves out).

## Per-package `cli.py` split

Mechanical pattern for every package: `cli.py` owns `argparse` setup and
subcommand dispatch (where relevant, e.g. `tapedeck load/unload/list`), and
calls into plain functions in the sibling modules. Nothing in the non-cli
modules should call `sys.exit()`, print `--help`, or otherwise assume it's
the entrypoint — that's `cli.py`'s job alone. Return values and raised
exceptions are how non-cli functions report success/failure; `cli.py`
translates those into exit codes and error messages.

This is mechanical for most files, since most `main()` functions already
just parse args and call a real function — the split is: hoist `main()`
into `cli.py`, keep everything else where it is, rename the file per the
target tree above (e.g. `spotify_to_csv.py` → `spotify_export.py`).

`organize/beets_import.py` and `organize/preimport.py` deserve extra care:
their functions already return structured data (the `report` dict) rather
than just printing — preserve that, since it's exactly the shape `core/`
will want to consume later.

## `core/` — from subprocess to in-process

`pipelines/download_songs.py` today shells out via `python -m
download.download_spotify`, etc., and only gets a shell exit code back. The
refactor changes the *mechanism*, not the *shape* of the workflow:

```python
# before (subprocess)
cmd = [sys.executable, '-m', 'download.download_spotify', '--url-file', ...]
subprocess.run(cmd)

# after (in-process)
from download.spotify_download import download_spotify
ok = download_spotify(url_file=..., output_dir=..., ...)
```

This requires every domain package's core functions to already be
`import`-able without triggering `argparse`/`sys.exit` side effects — which
falls out naturally once the `cli.py` split above is done everywhere.
`core/download_songs.py` and the new `core/sync.py` (promoting the
`playlists --apply --rescrape` README-documented flow to an actual function)
become the first two real workflows; `core/cli.py` can wrap both as
subcommands the same way `pipelines/download_songs.py` is invoked today, so
the CLI-facing behavior doesn't regress.

Benefits this unlocks, not required immediately but worth keeping in mind
while writing `core/`'s function signatures:
- Structured return values (counts, per-step results) instead of a bare exit
  code — useful for the CLI's own summary printing today, essential for
  `app/` later.
- No dependency on each step being separately invocable via `python -m` —
  useful if `core/` ever wants to call a step twice, or partially, or with
  in-memory data instead of a file on disk.
- Avoid designing `core/` functions around `print()` as the only progress
  channel — a browser app can't "watch a terminal." Doesn't need solving now
  (logging module vs. callback vs. poll — genuinely a later decision), but
  worth not accidentally foreclosing by hardcoding `print()` as the *only*
  way a step reports progress.

## `app/` — deferred, but shaped by everything above

Not part of this refactor pass. Once `lib/`, the four domain packages, and
`core/` are done, `app/` is meant to be a thin layer that:
- imports `lib/`, the domain packages, and `core/` directly (no subprocess,
  no shelling out to CLIs it doesn't own),
- runs locally as a browser app for manipulating the library,
- potentially streams the library out to Symfonium on a phone.

No architecture decisions for `app/` are being made now beyond "make sure
nothing below it assumes a terminal or a CLI invocation is the only way in."

## Decisions made explicitly during this planning pass

- `lib/` over multiple small top-level packages (`paths/`, `catalog/`, etc.)
  — one shared foundation, subfolders inside it where a concern (catalog)
  genuinely needs more than one file.
- `pipelines/` renamed to `core/`, not kept as a separate concept — same job,
  same eventual audience (the CLI today, `app/` later).
- `core/` sits *above* the four domain packages and *below* `app/`; it may
  call into a domain package directly for a single-step action, or into
  another `core/` function for a multi-step preset — `app/` isn't forced
  through `core/` for everything.
- Dual-case env var fallback is being dropped in favor of one canonical
  upper-case name per root, resolved in exactly one place (`lib/paths.py`).
- `retry.py`'s logic must be rebuilt from the README description — this is
  new-ish code, not a mechanical port, and should be written directly
  against `lib/paths.py` and `lib/text.py` rather than the old cross-package
  imports it used to have (`download.download_spotify._predict_output_filename`
  stays where it is since it's genuinely download-specific; the library-
  index/normalize calls move to `lib/`).
