"""lib.tags - read/write audio tags, and the crate-file grouping primitives
built on top of them.

this is the toolkit half of what used to be organize/cleanup.py: reading
tags, sanitizing filenames, walking a directory tree for audio files, and
picking a canonical albumartist/album for a group of files. organize.cleanup
now imports these and keeps only its regroup-in-place *policy* on top; so
does organize.preimport, and lib.catalog.indexer for the crate-wide index.
"""

import collections
import os
import re
import shutil
import sys

try:
    from mediafile import MediaFile
except ImportError:  # pragma: no cover
    sys.exit("mediafile not installed - run `uv sync` first (beets pulls it in).")

from lib.text import normalize_key

EXTENSIONS = ('.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aac')

_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|]')


def sanitize(s):
    """filesystem-safe path component from a tag string."""
    s = _ILLEGAL_RE.sub('', s or '')
    s = s.strip().rstrip('.')
    return s or '_'


def primary_token(raw):
    """first collaborator segment - "A & B" / "A & B & C" -> "A". narrower
    than lib.text.primary_artist: only splits on & or / (album-artist
    strings), not the full feat/x/vs/comma set used for track credits."""
    return re.split(r'\s*(?:&|/)\s*', raw or '', maxsplit=1)[0].strip()


def read_tags(path):
    """return a dict of {path, artist, albumartist, album, title, track,
    length} for one audio file, or None on read error. length is in
    seconds (0.0 if unavailable)."""
    try:
        m = MediaFile(path)
    except Exception:
        return None
    return {
        'path': path,
        'artist': (m.artist or '').strip(),
        'albumartist': (m.albumartist or '').strip(),
        'album': (m.album or '').strip(),
        'title': (m.title or '').strip(),
        'track': m.track or 0,
        'length': float(m.length) if m.length else 0.0,
    }


def write_tag(path, **fields):
    """write one or more MediaFile fields (e.g. albumartist='X') if they
    differ from the current value. generalizes the old write_albumartist."""
    try:
        m = MediaFile(path)
        changed = False
        for field, value in fields.items():
            current = getattr(m, field, None) or ''
            if normalize_key(current) != normalize_key(value):
                setattr(m, field, value)
                changed = True
        if changed:
            m.save()
    except Exception as e:
        print(f"  tag-write failed: {path} ({e})", file=sys.stderr)


def canonical_albumartist(files):
    """pick the folder label for an album group: dominant (albumartist|artist)
    string, else dominant primary collaborator, else "Various Artists".
    returns the original-cased label (not normalized)."""
    counts = collections.Counter()
    orig = {}
    for f in files:
        raw = (f['albumartist'] or f['artist'] or '').strip()
        if raw:
            k = normalize_key(raw)
            counts[k] += 1
            orig.setdefault(k, raw)
    total = sum(counts.values())
    if total:
        top, top_n = counts.most_common(1)[0]
        if top_n >= total * 0.5:
            return orig[top]
        pc = collections.Counter()
        porig = {}
        for f in files:
            raw = (f['albumartist'] or f['artist'] or '').strip()
            if not raw:
                continue
            p = primary_token(raw)
            k = normalize_key(p)
            pc[k] += 1
            porig.setdefault(k, p)
        if pc:
            ptop, ptop_n = pc.most_common(1)[0]
            if ptop_n >= total * 0.5:
                return porig[ptop]
    return 'Various Artists'


def dominant_album(files):
    """most common original-cased album string among the group's files."""
    c = collections.Counter()
    orig = {}
    for f in files:
        a = f['album']
        if a:
            c[normalize_key(a)] += 1
            orig.setdefault(normalize_key(a), a)
    if not c:
        return ''
    return orig[c.most_common(1)[0][0]]


def scan_audio(root_path, subdirs=('albums', 'singles')):
    """walk audio files under root_path. subdirs names each subdir to scan
    (default albums+singles), or subdirs=None to walk root_path recursively
    as a whole (used by preimport over an unorganized drop)."""
    files = []
    roots = [os.path.join(root_path, s) for s in subdirs] if subdirs else [root_path]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, dirs, fns in os.walk(root):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for fn in fns:
                if not fn.lower().endswith(EXTENSIONS):
                    continue
                entry = read_tags(os.path.join(dp, fn))
                if entry is None:
                    continue
                if not entry['title']:
                    entry['title'] = os.path.splitext(fn)[0]
                if not entry['artist']:
                    entry['artist'] = entry['albumartist'] or 'Unknown Artist'
                files.append(entry)
    return files


def safe_move(src, dst):
    """move src -> dst, creating parent dirs; rename on destination collisions."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.normpath(src) == os.path.normpath(dst):
        return
    if os.path.exists(dst):
        base, ext = os.path.splitext(dst)
        i = 2
        while os.path.exists(f"{base} ({i}){ext}"):
            i += 1
        dst = f"{base} ({i}){ext}"
    shutil.move(src, dst)
