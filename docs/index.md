---
icon: lucide/music
---

# tapebuilding

building and managing my personal music library.

## overview

five commands, one per package:

- [`core`](core.md): opinionated multi-step workflows stitching the others together (download + import + refresh in one pass, or a full sync)
- [`download`](download.md): export spotify playlists/liked songs, download from spotify/soundcloud/youtube, retry failures, pull soundbyte albums
- [`organize`](organize.md): turn raw downloads into a clean beets-managed crate
- [`playlists`](playlists.md): rebuild local `.m3u8`s from spotify playlists, matched against the crate
- [`tapedeck`](tapedeck.md): mirror a rotation subset of the crate to a synced device

each package owns its own `cli.py`; nothing below the cli layer calls `sys.exit()` or assumes it's being run from a terminal, so all of this is also directly importable.

## install

```bash
git clone https://github.com/three2semicolon/tapebuilding
cd tapebuilding
uv sync
```

installs `core`, `download`, `organize`, `playlists`, and `tapedeck` as console commands, editable.

## environment

set the variables in `.env` (see `.env.example`). see the [environment](environment.md) reference for the full list.

## source

docs source lives in this repo under [`docs/`](https://github.com/three2semicolon/tapebuilding/tree/main/docs). edit a page and click "edit this page" (top right) to propose a change.
