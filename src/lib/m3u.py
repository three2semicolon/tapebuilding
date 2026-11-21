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
        return "_"
    normalized = unicodedata.normalize("NFKD", name)
    ascii_str = normalized.encode("ASCII", "ignore").decode("ASCII")
    s = _WIN_ILLEGAL_RE.sub("", ascii_str)
    s = s.strip().rstrip(".")
    return s or "_"


def relativize(local_path, m3u_path):
    """local file path -> path relative to the .m3u8's folder, forward-slashed."""
    rel = os.path.relpath(local_path, start=os.path.dirname(m3u_path))
    return rel.replace("\\", "/")


def _ext_seconds(length):
    s = int(round(length or 0))
    return s if s > 0 else -1


def _clean_text(s):
    """drop newlines/tabs that would break #EXTINF - rare but fatal if present."""
    return re.sub(r"[\r\n\t]+", " ", s).strip()


def render(entries, m3u_path, source=None, edited=False):
    """entries: [{track_id, artist, title, length, rel, path, local, extinf?}]
    all already matched. returns the .m3u8 text.

    `source` writes a '#TAPEDECK-SOURCE:...' header after '#EXTM3U';
    `edited=True' writes '#TAPEDECK-EDITED:1'.

    Each entry's path line is `rel` if present (missing files survive a
    rewrite), otherwise `path` relativized against m3u_path.  `local=True`
    writes a '#TAPEDECK-LOCAL' marker before the entry.  When an entry
    carries its own 'extinf' (a pre-rendered '#EXTINF:...' line, e.g. from
    read_entries) and no artist/title are given, it is kept verbatim;
    otherwise '#EXTINF:<length>,<artist> - <title>' is rendered.
    """
    lines = ["#EXTM3U"]
    if source:
        lines.append(f"#TAPEDECK-SOURCE:{source}")
    if edited:
        lines.append("#TAPEDECK-EDITED:1")
    for e in entries:
        tid = (e.get("track_id") or "").strip()
        if e.get("local"):
            lines.append("#TAPEDECK-LOCAL")
        if tid:
            lines.append(f"#SPOTIFY:{tid}")
        extinf = e.get("extinf")
        artist = _clean_text(e.get("artist") or "")
        title = _clean_text(e.get("title") or "")
        if extinf and not artist and not title:
            lines.append(extinf)
        else:
            label = f"{artist} - {title}" if artist and title else (title or artist or "")
            lines.append(f"#EXTINF:{_ext_seconds(e.get('length') or 0)},{label}")
        rel = e.get("rel")
        if not rel and e.get("path"):
            rel = relativize(e["path"], m3u_path)
        lines.append(rel or "")
    return "\n".join(lines) + "\n"


def write_m3u8(m3u_path, entries, source=None, edited=False):
    """render + atomic write (tmp then os.replace) so a crash mid-write
    can't leave a half-written playlist. accepts source=/edited= for the
    #TAPEDECK-* headers."""
    text = render(entries, m3u_path, source=source, edited=edited)
    os.makedirs(os.path.dirname(m3u_path) or ".", exist_ok=True)
    tmp = m3u_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, m3u_path)
    return m3u_path


def read_entries(m3u_path):
    """read a .m3u8 -> (entries, source, edited).

    entries: [{track_id, artist, title, length, rel, path, exists, local,
    extinf?}] in file order.  #SPOTIFY/#EXTINF/#TAPEDECK-LOCAL attach to
    the next path line.

      - rel:   raw relative line as written (playlist-dir-relative)
      - path:  absolute normalized path, or None when the line doesn't
               resolve to a file on disk
      - exists: whether the file is on disk
      - local: whether a #TAPEDECK-LOCAL marker preceded this entry
      - extinf: the raw '#EXTINF:...' line if present, else None

    source: value of the '#TAPEDECK-SOURCE:' header ('' when absent).
    edited: whether '#TAPEDECK-EDITED:1' is present.

    Keep read_m3u8 for existing callers that only need the three lists.
    """
    entries = []
    source = ""
    edited = False
    if not os.path.exists(m3u_path):
        return entries, source, edited
    base = os.path.dirname(m3u_path)
    pending = {"track_id": "", "artist": "", "title": "", "length": 0, "local": False, "extinf": None}
    with open(m3u_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            if line.startswith("#TAPEDECK-SOURCE:"):
                source = line[len("#TAPEDECK-SOURCE:") :].strip()
                continue
            if line == "#TAPEDECK-EDITED:1":
                edited = True
                continue
            if line == "#TAPEDECK-LOCAL":
                pending["local"] = True
                continue
            if line.startswith("#SPOTIFY:"):
                pending["track_id"] = line[len("#SPOTIFY:") :].strip()
                continue
            if line.startswith("#EXTINF:"):
                rest = line[len("#EXTINF:") :]
                comma = rest.find(",")
                if comma >= 0:
                    try:
                        pending["length"] = int(rest[:comma].strip() or 0)
                    except ValueError:
                        pending["length"] = 0
                    pending["artist"], pending["title"] = _split_extinf_label(rest[comma + 1 :])
                else:
                    pending["length"] = int(rest.strip() or 0)
                pending["extinf"] = line
                continue
            if line.startswith("#"):
                continue
            # a path line
            rel = line.replace("\\", "/")
            abs_p = os.path.normpath(os.path.join(base, rel))
            exists = os.path.isfile(abs_p)
            entries.append(
                {
                    "track_id": pending["track_id"],
                    "artist": pending["artist"],
                    "title": pending["title"],
                    "length": pending["length"],
                    "rel": rel,
                    "path": abs_p if exists else None,
                    "exists": exists,
                    "local": pending["local"],
                    "extinf": pending["extinf"],
                }
            )
            pending = {"track_id": "", "artist": "", "title": "", "length": 0, "local": False, "extinf": None}
    return entries, source, edited


def _split_extinf_label(label):
    """split an #EXTINF label 'artist - title' into (artist, title)."""
    label = label.strip()
    if " - " in label:
        artist, title = label.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", label


def read_source(m3u_path):
    """read the first few lines of a .m3u8 -> its '#TAPEDECK-SOURCE:'
    value ('' when absent).  Only scans the header, so it's cheap to call
    for build.py's write guard."""
    if not os.path.exists(m3u_path):
        return ""
    with open(m3u_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i > 6:
                break
            line = line.strip()
            if line.startswith("#TAPEDECK-SOURCE:"):
                return line[len("#TAPEDECK-SOURCE:") :].strip()
            if line == "#EXTM3U":
                continue
    return ""


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
    result = {"track_ids": [], "existing": [], "missing": []}
    if not os.path.exists(m3u_path):
        return result
    base = os.path.dirname(m3u_path)
    with open(m3u_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#SPOTIFY:"):
                tid = line[len("#SPOTIFY:") :].strip()
                if tid:
                    result["track_ids"].append(tid)
                continue
            if line.startswith("#"):
                continue
            rel = line.replace("\\", "/")
            abs_p = os.path.normpath(os.path.join(base, rel))
            if os.path.isfile(abs_p):
                result["existing"].append(abs_p)
            else:
                result["missing"].append(rel)
    return result
