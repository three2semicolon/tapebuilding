#!/usr/bin/env python3
"""m3u - write extended .m3u8 playlists with a spotify-id comment line.

format (one entry per matched track, spotify playlist order preserved):
  #SPOTIFY:<track_id>
  #EXTINF:<seconds>,<artist> - <title>
  <relative_path>

paths are written forward-slashed and relative to the .m3u8's own folder, so the
file stays portable to any device that mirrors the crate tree via syncthing.
the `#SPOTIFY:<id>` comment is ignored by players but lets a future reverse-sync
(edits on a synced device -> spotify) recover track uris without re-resolving
filenames.

unresolved spotify rows are omitted from the .m3u8 (the playlist stays playable)
and logged to the unmatched handoff instead.
"""

import os
import re

_WIN_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name):
    """filesystem-safe playlist stem - readable, not underscored.
    strips the full windows-illegal set (incl. *) and trailing dots/spaces."""
    s = _WIN_ILLEGAL.sub('', name or '')
    s = s.strip().rstrip('.')
    return s or '_'


def relativize(local_path, m3u_path):
    """local file path -> path relative to the .m3u8's folder, forward-slashed."""
    rel = os.path.relpath(local_path, start=os.path.dirname(m3u_path))
    return rel.replace('\\', '/')


def _ext_seconds(length):
    s = int(round(length or 0))
    return s if s > 0 else -1


def render(entries, m3u_path):
    """entries: [{track_id, artist, title, length, path}] all already matched.
    returns the .m3u8 text. paths rendered relative to m3u_path."""
    lines = ['#EXTM3U']
    for e in entries:
        tid = (e.get('track_id') or '').strip()
        artist = _clean_text(e.get('artist') or '')
        title = _clean_text(e.get('title') or '')
        label = f"{artist} - {title}" if artist and title else (title or artist or '')
        rel = relativize(e['path'], m3u_path)
        if tid:
            lines.append(f"#SPOTIFY:{tid}")
        lines.append(f"#EXTINF:{_ext_seconds(e.get('length') or 0)},{label}")
        lines.append(rel)
    return '\n'.join(lines) + '\n'


def _clean_text(s):
    """drop newlines/tabs that would break #EXTINF - rare but fatal if present."""
    return re.sub(r'[\r\n\t]+', ' ', s).strip()


def write_m3u8(m3u_path, entries):
    """render + atomic write (tmp then os.replace) so a crash mid-write can't
    leave a half-written playlist."""
    text = render(entries, m3u_path)
    os.makedirs(os.path.dirname(m3u_path) or '.', exist_ok=True)
    tmp = m3u_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    os.replace(tmp, m3u_path)
    return m3u_path


def parse_spotify_ids(m3u_path):
    """recover the ordered list of spotify track ids embedded in a written .m3u8.
    the future reverse-sync uses this to diff a (possibly hand-edited) synced
    playlist back against spotify membership."""
    ids = []
    if not os.path.exists(m3u_path):
        return ids
    with open(m3u_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#SPOTIFY:'):
                tid = line[len('#SPOTIFY:'):].strip()
                if tid:
                    ids.append(tid)
    return ids
