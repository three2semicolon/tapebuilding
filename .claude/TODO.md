# tapebuilding — todo

The `pipelines/` → `core/` refactor (`lib/` foundation + per-package
`cli.py` split + in-process `core/`) is complete. See `PACKAGE_OVERVIEW.md`
for current state and `README.md` for usage. What's left is genuinely
unscheduled work, not a checklist to execute in order.

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
