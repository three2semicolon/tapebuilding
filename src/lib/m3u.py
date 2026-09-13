"""lib.m3u - write and read extended .m3u8 playlists.

format (one entry per matched track, spotify playlist order preserved):
  #SPOTIFY:<track_id>
  #EXTINF:<seconds>,<artist> - <title>
  <relative_path>

paths are written forward-slashed, relative to the .m3u8's own folder, so
the file stays portable across any device that mirrors the crate tree via
syncthing. the #SPOTIFY:<id> comment is ignored by players but lets a future
reverse-sync recover track uris without re-resolving filenames.

read_m3u8() replaces two previously separate readers (playlists/m3u.py's
parse_spotify_ids, tapedeck/resolve.py's private _parse_m3u8) with one
function returning everything either caller needs.
"""

import os
import re
import unicodedata

_WIN_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name):
    """filesystem-safe playlist stem - readable, not underscored.
    transliterates non-ascii characters to ascii, then strips illegal chars."""
    if not name:
        return '_'
    normalized = unicodedata.normalize('NFKD', name)
    ascii_str = normalized.encode('ASCII', 'ignore').decode('ASCII')
    s = _WIN_ILLEGAL_RE.sub('', ascii_str)
    s = s.strip().rstrip('.')
    return s or '_'


def relativize(local_path, m3u_path):
    """local file path -> path relative to the .m3u8's folder, forward-slashed."""
    rel = os.path.relpath(local_path, start=os.path.dirname(m3u_path))
    return rel.replace('\\', '/')


def _ext_seconds(length):
    s = int(round(length or 0))
    return s if s > 0 else -1


def _clean_text(s):
    """drop newlines/tabs that would break #EXTINF - rare but fatal if present."""
    return re.sub(r'[\r\n\t]+', ' ', s).strip()


def render(entries, m3u_path):
    """entries: [{track_id, artist, title, length, path}] all already
    matched. returns the .m3u8 text, paths rendered relative to m3u_path."""
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


def write_m3u8(m3u_path, entries):
    """render + atomic write (tmp then os.replace) so a crash mid-write
    can't leave a half-written playlist."""
    text = render(entries, m3u_path)
    os.makedirs(os.path.dirname(m3u_path) or '.', exist_ok=True)
    tmp = m3u_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    os.replace(tmp, m3u_path)
    return m3u_path


def read_m3u8(m3u_path):
    """read a written .m3u8 -> {'track_ids': [...], 'existing': [...],
    'missing': [...]}.

    track_ids   - ordered list of #SPOTIFY:<id> values (for a future
                  reverse-sync; was m3u.parse_spotify_ids).
    existing    - path lines that resolve to a real file on disk, as
                  absolute paths (resolved relative to the .m3u8's own
                  folder).
    missing     - path lines that don't resolve to a file, as the raw
                  relative string from the file (was tapedeck's private
                  _parse_m3u8, first element renamed for clarity).
    """
    result = {'track_ids': [], 'existing': [], 'missing': []}
    if not os.path.exists(m3u_path):
        return result
    base = os.path.dirname(m3u_path)
    with open(m3u_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('#SPOTIFY:'):
                tid = line[len('#SPOTIFY:'):].strip()
                if tid:
                    result['track_ids'].append(tid)
                continue
            if line.startswith('#'):
                continue
            rel = line.replace('\\', '/')
            abs_p = os.path.normpath(os.path.join(base, rel))
            if os.path.isfile(abs_p):
                result['existing'].append(abs_p)
            else:
                result['missing'].append(rel)
    return result
