# playlists

build and maintain local `.m3u8` files from spotify playlists, resolving each
track to a file in the crate.

## the `playlists` command

```
uv run playlists --playlist "_obs"          # preview one (no files written)
uv run playlists --apply --playlist "_obs"  # write it
uv run playlists --apply                     # build every playlist you own (default)
uv run playlists --apply --all              # include followed/shared lists
uv run playlists --apply --rescrape --covers   # refresh from spotify + grab art
uv run playlists --reindex                  # rebuild the local index sidecar
```

flow: read `PLAYLISTS_PATH/exports/playlist_tracks.csv` (membership; row order is
spotify's playlist order) → resolve each track to a crate file → write one
`.m3u8` per playlist into `PLAYLISTS_PATH`. re-running rebuilds the files from
current membership, so adds/removes/reorders on spotify are the "update". songs
may be in multiple playlists.

### path style
`.m3u8` paths are written **relative to the playlist file's own folder**
(`../albums/…`, `../singles/…`, `../soundtracks/…`). this stays portable across
any device that mirrors the crate via syncthing — as long as the `.m3u8` lives
somewhere inside the crate tree (`PLAYLISTS_PATH` is `Y:/music/crate/playlists`
by default). if you point `--playlists-path` outside the crate, the relative
paths won't resolve.

### the spotify id comment
each entry carries a `#SPOTIFY:<track_id>` line players ignore. it's there so a
future reverse-sync (edits on a synced device → back into spotify) can recover
track uris without re-resolving filenames. see `playlists/m3u.py:parse_spotify_ids`.

### matching
the exports carry no ISRC and the library is mostly beat tapes/bootlegs (beets
runs with `quiet_fallback: asis`), so matching is by name against tags read off
the filesystem with `mediafile` — *not* beets.db, which doesn't index the
`soundtracks/` tree. tiers: exact-title + primary-artist → exact-title + any
artist → exact-title + album → fuzzy title (4-char prefix, ratio ≥ 0.92). the
local index is cached to `PLAYLISTS_PATH/exports/.playlist_index.jsonl`; run
`--reindex` after importing new music (mirrors `cleanup --rebuild-db`).

### unmatched handoff
tracks not found locally are logged to `PLAYLISTS_PATH/exports/unmatched.csv`
and `unmatched_urls.txt` (one spotify url per line). the latter is consumable by
the existing downloader:
```
uv run spotify -u PLAYLISTS_PATH/exports/unmatched_urls.txt
```

### scope
- default `--mine` builds only playlists you own (`owner == SPOTIFY_USER_ID`).
- `--all` builds followed/shared lists too.
- `-p/--playlist` (repeatable) builds specific playlists by name or spotify id;
  overrides the scope.
- `--rescrape` re-runs `export --mine` first to refresh the spotify csvs.
- `--covers` (auto-useful with `--rescrape`) downloads each playlist's cover to
  `<name>.jpg` beside the `.m3u8`; needs spotify auth (the csvs have no image url).

## env
read from `.env` (dual-case, per the repo convention): `ARCHIVE_PATH` (crate),
`PLAYLISTS_PATH` (`.m3u8` destination), `SPOTIFY_USER_ID` (for `--mine`), and the
`SPOTIFY_*` credentials (for `--rescrape` / `--covers`).

## planned (not yet built)
- reverse-sync: parse a synced/edited `.m3u8` back into spotify membership and
  add/remove on spotify (needs `playlist-modify-*` scope; the `#SPOTIFY:` comment
  already enables the uri recovery).
- rotation/scheduling of `.m3u8`s into `TAPEDECK_PATH`.
- a beets `beet ls -f` fast-path index source (the mediafile walk is the
  complete path; beets.db alone misses soundtracks).
