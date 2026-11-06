---
icon: lucide/music-2
---

# playlists

rebuild local `.m3u8` files from spotify or soundcloud playlists, matched against the crate.

rescrapes service data (optionally scoped to specific playlists) and rebuilds each playlist's `.m3u8` against the crate, using the same tiered matcher as `tapedeck`. writes unmatched tracks to `unmatched.csv` / `unmatched_urls.txt` (feeds back into `download spotify -u` or `download soundcloud -u`) rather than failing the run. `--covers` downloads each playlist's cover art (spotify only).

for spotify, `--service spotify` (default) rescrapes owned playlists via the spotify api. for soundcloud, `--service soundcloud` rescrapes all sets for `soundcloud_user` unless `soundcloud_playlists_file` is set, in which case only the sets listed in that file are re-scraped.

`core sync` is this command's `--apply --rescrape` flow, promoted to its own entry point. for the full `playlists` flag set (dry-run/preview mode, `-p`/`--all`/`--mine` selection, `--service`, etc.) run `playlists --help`.

## unmatched handoff

tracks that can't be matched against the crate are written to `unmatched.csv` / `unmatched_urls.txt` in the service-specific exports directory, so they can be downloaded later with `download spotify -u unmatched_urls.txt` or `download soundcloud -u unmatched_urls.txt`.
