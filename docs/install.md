---
icon: lucide/download
---

# install

```bash
git clone https://github.com/three2semicolon/tapebuilding
cd tapebuilding
uv sync
```

installs `core`, `download`, `organize`, `playlists`, and `tapedeck` as console commands, editable.

## requirements

- python >= 3.14 (see `.python-version`)
- [uv](https://docs.astral.sh/uv/) for dependency management
- [ffmpeg](https://ffmpeg.org/) on `PATH`, or set `ffmpeg_path` in `.env`
- a spotify client id/secret (or a `spotify_sp_dc` cookie for spotapi auth)

## environment file

copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

uppercase-only env vars are used. the old dual-case fallback has been dropped.
