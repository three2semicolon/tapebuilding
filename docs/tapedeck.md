---
icon: lucide/cassette-tape
---

# tapedeck

mirror a rotation subset of the crate to a synced device.

loads/unloads/lists a subset of the crate, albums, songs, soundtracks, or whole playlists, mirrored 1:1 by crate-relative path into `tapedeck_path`, for offline/roaming playback on another device. no downloading, no spotify involved; copies (or hardlinks, same-volume only) files that already exist in the crate.

dry-run by default, matching the rest of the repo's `--apply` convention. unloading a playlist only removes a track if no other loaded playlist still references it (refcounted).

```bash
tapedeck load ...
tapedeck unload ...
tapedeck list
```

run `tapedeck --help` for the full `load`/`unload`/`list` flag set (kind/spec syntax, `--apply`, `--link`, `--overwrite`, `--verbose`).
