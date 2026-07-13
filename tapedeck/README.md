# tapedeck

A rotation of music synced across devices (local, using syncthing). This is where individual devices store their current rotation for immediate playback and seamless hand-offs.

The synced path is controlled by the `TAPEDECK_PATH` environment variable (default: `~/music/tapedeck`). Place `.m3u`/`.m3u8` playlist files here - they'll mirror in real time to any device configured for syncthing.

This is in-progress - more automated rotation features coming soon.
