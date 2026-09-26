"""organize.preimport.plan - the read-only half of the preimport pass:
scan <input> and <crate>/albums and decide where every album-group file
should end up (merge into an existing crate album, stage a new album
folder, or pass through as a singleton). apply.py's stage() calls
index_existing_albums() and build_plan() below, then performs the
actual moves/tag-writes.

three outcomes per group (= album tag shared):
  merge   - existing crate folder matched: move INTO it, tag with its albumartist
  stage   - no match, >=2 tracks: new folder under <input>/albums/, tag canonical aa
  pass    - no match, lone track: leave where it is for the beets singles pass
files with no album tag are singletons - left untouched for the singles pass.
"""

import os

from lib.tags import EXTENSIONS, canonical_albumartist, dominant_album, read_tags, sanitize
from lib.text import normalize_key
from organize.cleanup import is_unrelated_va_collision


def _first_audio(folder):
    """first audio file under folder (sorted for determinism), or None."""
    for dp, dirs, fns in os.walk(folder):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for fn in sorted(fns):
            if fn.lower().endswith(EXTENSIONS):
                return os.path.join(dp, fn)
    return None


def index_existing_albums(crate):
    """map (norm(albumartist), norm(album)) -> (folder_path, albumartist_raw)
    for every album folder under <crate>/albums, read off one file's tags.

    an album name collision across multiple folders marks the key None
    (ambiguous) so stage() refuses to merge against it - staging a new folder is
    always safer than risking a wrong merge of two different real albums that
    happen to share a normalized name."""
    root = os.path.join(crate, 'albums')
    if not os.path.isdir(root):
        return {}
    idx = {}
    for d in sorted(os.listdir(root)):
        full = os.path.join(root, d)
        if not os.path.isdir(full):
            continue
        rep = _first_audio(full)
        if not rep:
            continue
        tags = read_tags(rep)
        if tags is None:
            continue
        albumartist, album = tags['albumartist'], tags['album']
        if not album:
            continue
        key = (normalize_key(albumartist), normalize_key(album))
        if key in idx:
            idx[key] = None  # ambiguous: >=2 existing folders match -> never merge
        else:
            idx[key] = (full, albumartist or '')
    return idx


def _track_label(i, m):
    """two-digit track number - the tag's track, else 1-based position in group."""
    n = m['track'] or (i + 1)
    return f"{int(n) if n else i + 1:02d}"


def _existing_titles(folder):
    """set of normalized titles for every audio file already in <folder>, so a
    merge into an existing album can skip tracks the crate already has (e.g. an
    mp3 straggler of a track present as flac) instead of parking a second-format
    copy beside the original (beets' duplicate_action:skip wouldn't catch a
    same-album intra-folder duplicate)."""
    titles = set()
    for dp, dirs, fns in os.walk(folder):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for fn in sorted(fns):
            if not fn.lower().endswith(EXTENSIONS):
                continue
            t = read_tags(os.path.join(dp, fn))
            if t and t['title']:
                titles.add(normalize_key(t['title']))
    return titles



def _member_name(i, m, folder_path, seen):
    """NN - Artist - Title.ext, disambiguated on collision within the folder.
    matches beets' default path template so the staged name is what beets keeps."""
    ext = os.path.splitext(m['path'])[1]
    name = f"{_track_label(i, m)} - {sanitize(m['artist'])} - {sanitize(m['title'])}{ext}"
    taken = seen.setdefault(folder_path, set())
    base, sfx = os.path.splitext(name)
    c = 2
    while name.lower() in taken:
        name = f"{base} ({c}){sfx}"
        c += 1
    taken.add(name.lower())
    return name


def build_plan(groups, unorganized, crate, idx):
    """decide a destination + albumartist tag for every album-group file.
    returns a report dict + move/tag-write lists (src, dst, albumartist_to_write).

    three outcomes per group (= album tag shared):
      merge   - existing crate folder matched: move INTO it, tag with its albumartist
      stage   - no match, >=2 tracks: new folder under <input>/albums/, tag canonical aa
      pass    - no match, lone track: leave where it is for the beets singles pass
    files with no album tag are singletons - left untouched for the singles pass."""
    staging_root = os.path.join(unorganized, 'albums')

    staged_moves = []     # (src, dst, aa_for_tag)
    merged_moves = []     # (src, dst, aa_for_tag)
    dup_moves = []        # (src,) - tracks the target album already owns; -> duplicates/
    tag_writes = []       # (src, aa_for_tag)
    seen = {}             # folder -> set of lowercased names (collision guard)
    existing_titles_cache = {}  # folder_path -> set(norm(title)) (lazy, merge targets only)
    report = {
        'scanned': sum(len(v) for v in groups.values()),
        'staged_folders': [],
        'merged_folders': [],
        'merged_tracks': 0,
        'split_groups': [],
        'duplicates': [],
        'tag_writes': 0,
        'singletons': 0,
        'ambiguous': [],
    }

    for (kind, _), members in groups.items():
        if kind == 'single':
            # no album tag at all -> true singleton, leave for the singles pass
            report['singletons'] += len(members)
            continue

        aa = canonical_albumartist(members)
        album = dominant_album(members)

        if is_unrelated_va_collision(aa, members):
            report['singletons'] += len(members)
            report['split_groups'].append((album, len(members)))
            continue

        key = (normalize_key(aa), normalize_key(album))
        entry = idx.get(key) if idx else None
        # >=2 existing crate folders normalize to this (aa, album) -> idx flagged it
        # None -> can't safely merge; stage (if multi-track) or leave as singleton,
        # but record it so the user sees why a would-be merge was declined.
        ambiguous = bool(idx) and key in idx and idx[key] is None

        if entry is not None:
            # merge into an existing crate album folder
            folder_path, existing_aa = entry
            aa_for_tag = existing_aa or aa
            have = existing_titles_cache.setdefault(
                folder_path, _existing_titles(folder_path))
            merged_here = 0
            for i, m in enumerate(members):
                # skip tracks the album already owns (e.g. an mp3 straggler of a
                # track present as flac) - quarantine rather than create a
                # cross-format dup beside the original.
                if normalize_key(m['title']) in have:
                    dup_moves.append((m['path'],))
                    report['duplicates'].append(
                        (m['path'], folder_path, m['title']))
                    continue
                dst = os.path.join(folder_path, _member_name(i, m, folder_path, seen))
                if os.path.normpath(dst) != os.path.normpath(m['path']):
                    merged_moves.append((m['path'], dst, aa_for_tag))
                if normalize_key(m['albumartist'] or '') != normalize_key(aa_for_tag):
                    tag_writes.append((m['path'], aa_for_tag))
                merged_here += 1
            if merged_here:
                report['merged_folders'].append(folder_path)
            report['merged_tracks'] += merged_here
        elif len(members) >= 2:
            # no existing match, multi-track -> stage a new album folder for pass 1
            folder_name = sanitize(f"{aa} - {album}") or 'Unknown Album'
            folder_path = os.path.join(staging_root, folder_name)
            for i, m in enumerate(members):
                dst = os.path.join(folder_path, _member_name(i, m, folder_path, seen))
                if os.path.normpath(dst) != os.path.normpath(m['path']):
                    staged_moves.append((m['path'], dst, aa))
                if normalize_key(m['albumartist'] or '') != normalize_key(aa):
                    tag_writes.append((m['path'], aa))
            report['staged_folders'].append(folder_path)
            if ambiguous:
                report['ambiguous'].append((aa, album))
        else:
            # lone track of an album we don't have -> behaves like a singleton
            report['singletons'] += 1
            if ambiguous:
                report['ambiguous'].append((aa, album))

    return report, staged_moves, merged_moves, dup_moves, tag_writes


