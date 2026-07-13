# pipelines

opinionated, multi-step workflows that stitch the single-purpose clis in
`download/`, `organize/`, and `playlists/` into one command. each pipeline is a
thin orchestrator - the real work is done by the existing tools, so the flags
you already know (`--apply`, `--archive-path`, dry-run) carry straight through.

run these from the repo root with `uv run`.

## sync - export spotify, build .m3u8, list what's missing

there's no wrapper for sync because `playlists` already does all three steps:
rescrape spotify, build every local `.m3u8`, and hand off the tracks you don't
have. the "sync" pipeline is just the one command:

```
uv run playlists --apply --rescrape --archive-path Y:/music/crate
```

what it does, in order:
  1. `--rescrape` re-runs `export --mine` → refreshes `playlists.csv` +
     `playlist_tracks.csv` under `PLAYLISTS_PATH/exports`.
  2. every playlist you own is resolved to crate files and written to a `.m3u8`
     in `PLAYLISTS_PATH`.
  3. tracks not found locally → `unmatched.csv` + `unmatched_urls.txt` in
     `PLAYLISTS_PATH/exports`. feed the urls back in:
     `uv run spotify -u PLAYLISTS_PATH/exports/unmatched_urls.txt`.

common variants:

```
uv run playlists --rescrape -p "_obs"            # rescrape just _obs, then preview it
uv run playlists --apply --rescrape -p "_obs"    # ...and write it
uv run playlists --apply --all --rescrape         # include followed/shared lists
uv run playlists --apply --reindex                # rebuild the index after importing new music
uv run playlists                                 # dry run (default): preview only
```

see `playlists/README.md` for the full flag list and matching details.

## download_songs - download, import, refresh in one pass

`pipelines/download_songs.py` runs the download workflow end to end: pull urls
with `spotify`, import the new files into the crate with `beets-import`, then
rebuild the `.m3u8`s with `playlists --reindex` so the new tracks turn up. it
shells out to those three clis, so each step keeps its own argparse/env/dry-run.

```
uv run pipelines/download_songs.py urls.txt --apply                              # full pass
uv run pipelines/download_songs.py urls.txt --apply --archive-path Y:/music/crate
uv run pipelines/download_songs.py "https://open.spotify.com/track/..." --apply  # one url
uv run pipelines/download_songs.py urls.txt --apply --only download               # download only
uv run pipelines/download_songs.py --apply --only playlists                       # just refresh, no source
uv run pipelines/download_songs.py urls.txt                                        # dry run (default)
```

the source can be:
  - a `.txt` (one url per line), a `.csv` (needs a `spotify_url` column), or a
    dir of `.csv`s - same inputs `spotify -u` accepts.
  - a single spotify url - written to a temp file and passed in for you.

the three steps:
  1. `spotify -u <source> -o <drop>` - spotdl the urls into `<crate>/unorganized`.
  2. `beets-import -i <drop> -o <crate>` - two-pass import (albums/ + singles/)
     with preimport staging.
  3. `playlists --apply --archive-path <crate> --reindex` - rebuild the `.m3u8`s.

flags:
  - `--apply` - do it for real. default is a dry run that prints the exact child
    commands and runs none of them (zero side effects). for a step's own detailed
    preview, run that child directly - `beets-import --dry-run`, or `playlists`
    without `--apply`.
  - `--only` (repeatable) - restrict to `download`, `import`, and/or `playlists`;
    default is all three, always run in that order.
  - `--archive-path` - crate root (default `$ARCHIVE_PATH`); forwarded to every step.
  - `--input` / `-i` - staging drop for downloads (default `<crate>/unorganized`,
    the dir `beets-import` already expects).
  - `--format` / `--bitrate` - forwarded to `spotify` (default `mp3` / `320k`).
  - `--verbose` - echo each sub-command and forward `--verbose` to the children.

the reason `download_songs` has a wrapper when sync doesn't: it chains three
different clis with one archive, one dry-run, and one source - worth a single
command. sync only needed the one `playlists` call, so a wrapper would just
re-name its flags.

### the manual hunt loop

`retry --report-csv manual_hunt.csv` (see `download/README.md`) drops a
named/sorted sheet of still-missing tracks. you can hand-pick urls into a small
`.txt` of your own and feed it straight back in:

```
uv run pipelines/download_songs.py my_picks.txt --apply
```

## env

both paths come from `.env` (see `.env.example`): `ARCHIVE_PATH` (crate root)
and `PLAYLISTS_PATH` (`.m3u8` destination). the spotify creds are only needed
for the rescrape / playlist-build steps - the bare download + import chain
runs without them.
