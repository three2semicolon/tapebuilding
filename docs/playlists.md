---
icon: lucide/music-2
---

# playlists

rebuild local `.m3u8` files from spotify playlists, matched against the crate.

rescrapes spotify (optionally scoped to specific playlists) and rebuilds each owned playlist's `.m3u8` against the crate, using the same tiered matcher as `tapedeck`. writes unmatched tracks to `unmatched.csv` / `unmatched_urls.txt` (feeds back into `download spotify -u`) rather than failing the run. `--covers` downloads each playlist's cover art.

`core sync` is this command's `--apply --rescrape` flow, promoted to its own entry point. for the full `playlists` flag set (dry-run/preview mode, `-p`/`--all`/`--mine` selection, etc.) run `playlists --help`.

## unmatched handoff

tracks that can't be matched against the crate are written to `unmatched.csv` / `unmatched_urls.txt` in the exports directory, so they can be downloaded later with `download spotify -u unmatched_urls.txt`.
