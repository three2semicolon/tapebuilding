---
icon: lucide/variable
---

# environment

variables are set in `.env` (see `.env.example`). uppercase only. the old dual-case fallback (`archive_path`/`archive_path`) has been dropped.

| variable | purpose |
|----------|---------|
| `archive_path` | crate root. has a convenience default almost everywhere, except `organize import` / `organize cleanup`, which require it explicitly (no fallback) since both move files on disk. |
| `playlists_path` | where `.m3u8`s + exports live. required, no fallback. |
| `tapedeck_path` | sync target for `tapedeck`. defaults to a convenience path. |
| `ffmpeg_path` | ffmpeg executable, if not already on `PATH`. |
| `spotify_client_id`, `spotify_client_secret` | spotify api client id/secret (official web api oauth flow). |
| `spotify_redirect_uri` | oauth redirect (default `http://127.0.0.1:8888/callback`). |
| `spotify_sp_dc` | your browser's `sp_dc` cookie (obtained after logging into spotify). when set, auth uses spotapi instead of oauth, no spotify premium needed. when unset, falls back to the official web api oauth flow. |
| `firebase_project_id`, `firebase_credentials_path` | for `download soundbyte`. |

copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```
