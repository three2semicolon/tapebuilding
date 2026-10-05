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
from dataclasses import dataclass
from typing import List, Tuple

from lib.tags import EXTENSIONS, canonical_album, canonical_albumartist, dominant_album, find_duplicates, read_tags, sanitize
from lib.text import normalize_album, normalize_key, split_artists, group_key, group_album_key, render_credit
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
    """map (albumartist_raw, album_raw) -> (folder_path, albumartist_raw, album_raw)
    for every album folder under <crate>/albums, read off one file's tags.

    Bug 3b: store raw albumstring and albumartiststring instead of normalized versions
    so preimport merges can compute canonical_album() over incoming ∪ existing.

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
        # Bug 3b: store raw strings instead of normalized
        # But use normalized key for collision detection
        norm_key = (normalize_album(albumartist or ''), normalize_album(album or ''))
        raw_key = (albumartist or '', album or '')
        if norm_key in idx:
            idx[norm_key] = None  # ambiguous: >=2 existing folders match -> never merge
        else:
            idx[norm_key] = (full, albumartist or '', album or '')
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


@dataclass
class Plan:
    """Dataclass for build_plan return value."""
    report: dict
    staged_moves: List[Tuple[str, str, str]]  # (src, dst, aa_for_tag)
    merged_moves: List[Tuple[str, str, str]]  # (src, dst, aa_for_tag)
    dup_moves: List[Tuple[str]]               # (src,) - tracks the target album already owns
    tag_writes: List[Tuple[str, str]]         # (src, aa_for_tag)
    album_tag_writes: List[Tuple[str, str]]   # (src, album)


def build_plan(groups, unorganized, crate, idx):
    """decide a destination + albumartist + album tag for every album-group file.
    returns Plan dataclass.

    three outcomes per group (= album tag shared):
      merge   - existing crate folder matched: move INTO it, tag with its albumartist
      stage   - no match, >=2 tracks: new folder under <input>/albums/, tag canonical aa
      pass    - no match, lone track: leave where it is for the beets singles pass
    files with no album tag are singletons - left untouched for the singles pass."""
    staging_root = os.path.join(unorganized, 'albums')
    singles_dir = os.path.join(crate, 'singles')

    staged_moves = []     # (src, dst, aa_for_tag)
    merged_moves = []     # (src, dst, aa_for_tag)
    dup_moves = []        # (src,) - tracks the target album already owns; -> duplicates/
    tag_writes = []       # (src, aa_for_tag)
    album_tag_writes = []   # (src, album)
    singleton_moves = []  # (src, dst) - singleton moves
    noop = 0              # number of files already in place
    seen = {}             # folder -> set of lowercased names (collision guard within folder)
    seen_staged = set()   # set of lowercased staged folder names (collision guard)
    existing_titles_cache = {}  # folder_path -> set(norm(title)) (lazy, merge targets only)
    seen_singletons = set()  # Track lowercase destination paths for singleton collision detection
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

        if is_unrelated_va_collision(members):
            report['singletons'] += len(members)
            report['split_groups'].append((album, len(members)))
            continue

        # Bug 3b: use raw album string for lookup, but compute canonical_album() over incoming ∪ existing
        album_raw = members[0]['album'] or ''
        aa_raw = members[0]['albumartist'] or members[0]['artist'] or ''
        key = (aa_raw, album_raw)
        entry = idx.get(key) if idx else None

        # Keep-existing-folder rule: check for case-insensitive match in existing crate albums
        existing_folder_match = None
        if entry is None and idx:
            for (norm_artist, norm_album), value in idx.items():
                if value is not None:  # Not ambiguous
                    (full_path, raw_artist, raw_album) = value
                    if raw_artist.lower() == aa_raw.lower() and raw_album.lower() == album_raw.lower():
                        existing_folder_match = (full_path, raw_artist, raw_album)
                        break

        # >=2 existing crate folders normalize to this (aa, album) -> idx flagged it
        # None -> can't safely merge; stage (if multi-track) or leave as singleton,
        # but record it so the user sees why a would-be merge was declined.
        norm_key = (normalize_album(aa_raw or ''), normalize_album(album_raw or ''))
        ambiguous = bool(idx) and norm_key in idx and idx[norm_key] is None

        # Record ambiguous keys for the report
        if ambiguous:
            report['ambiguous'].append((aa_raw or '', album_raw or ''))

        if entry is not None or existing_folder_match is not None:
            # merge into an existing crate album folder
            if entry is not None:
                folder_path, existing_aa, existing_album = entry
            else:
                folder_path, existing_aa, existing_album = existing_folder_match
            aa_for_tag = existing_aa or aa
            # Bug 3b: compute canonical_album() over incoming ∪ existing
            all_albums = [m['album'] or '' for m in members] + [existing_album]
            canonical_album_val = canonical_album([{'album': alb} for alb in all_albums if alb])
            have = existing_titles_cache.setdefault(
                folder_path, _existing_titles(folder_path))
            merged_here = 0
            for i, m in enumerate(members):
                # Bug 14: replace preimport duplicate check with find_duplicates()
                # Check for duplicates within the incoming group first
                incoming_duplicates = find_duplicates(members)
                # Flatten the duplicate groups to get a set of duplicate file paths
                duplicate_paths = set()
                for dup_group in incoming_duplicates:
                    for dup_file in dup_group:
                        duplicate_paths.add(dup_file['path'])

                # skip tracks the album already owns (e.g. an mp3 straggler of a
                # track present as flac) - quarantine rather than create a
                # cross-format dup beside the original.
                # Also skip tracks that are duplicates within the incoming group
                if normalize_key(m['title']) in have or m['path'] in duplicate_paths:
                    dup_moves.append((m['path'],))
                    report['duplicates'].append(
                        (m['path'], folder_path, m['title']))
                    continue
                dst = os.path.join(folder_path, _member_name(i, m, folder_path, seen))
                if os.path.normpath(dst) != os.path.normpath(m['path']):
                    merged_moves.append((m['path'], dst, aa_for_tag))
                if normalize_key(m['albumartist'] or '') != normalize_key(aa_for_tag):
                    tag_writes.append((m['path'], aa_for_tag))
                if normalize_key(m['album'] or '') != normalize_key(canonical_album_val):
                    album_tag_writes.append((m['path'], canonical_album_val))
                merged_here += 1
            # album tag writes: enforce the dominant album string so all files in group agree
            for m in members:
                if normalize_key(m['album'] or '') != normalize_key(album):
                    album_tag_writes.append((m['path'], album))
            if merged_here:
                report['merged_folders'].append(folder_path)
            report['merged_tracks'] += merged_here
        elif len(members) >= 2:
            # Bug 5: remove Various Artists override - do not override Various Artists based on raw artist tags
            # no existing match, multi-track -> stage a new album folder for pass 1
            folder_name = sanitize(f"{render_credit(aa)} - {album}") or 'Unknown Album'
            folder_path = os.path.join(staging_root, folder_name)

            # Check for collisions and disambiguate if needed
            name = folder_name
            c = 2
            while os.path.normpath(os.path.join(staging_root, name)).lower() in seen_staged:
                name = f"{os.path.splitext(folder_name)[0]} ({c}){os.path.splitext(folder_name)[1]}"
                c += 1
            seen_staged.add(os.path.normpath(os.path.join(staging_root, name)).lower())

            have = set()
            staged_here = 0
            for i, m in enumerate(members):
                # Bug 14: replace preimport duplicate check with find_duplicates()
                # Check for duplicates within the incoming group first
                incoming_duplicates = find_duplicates(members)
                # Flatten the duplicate groups to get a set of duplicate file paths
                duplicate_paths = set()
                for dup_group in incoming_duplicates:
                    for dup_file in dup_group:
                        duplicate_paths.add(dup_file['path'])

                # skip tracks the album already owns (e.g. an mp3 straggler of a
                # track present as flac) - quarantine rather than create a
                # cross-format dup beside the original.
                # Also skip tracks that are duplicates within the incoming group
                if normalize_key(m['title']) in have or m['path'] in duplicate_paths:
                    dup_moves.append((m['path'],))
                    report['duplicates'].append(
                        (m['path'], folder_path, m['title']))
                    continue
                dst = os.path.join(folder_path, _member_name(i, m, folder_path, seen))
                if os.path.normpath(dst) != os.path.normpath(m['path']):
                    staged_moves.append((m['path'], dst, aa))
                if normalize_key(m['albumartist'] or '') != normalize_key(aa):
                    tag_writes.append((m['path'], aa))
                if normalize_key(m['album'] or '') != normalize_key(album):
                    album_tag_writes.append((m['path'], album))
                have.add(normalize_key(m['title']))
                staged_here += 1
            if staged_here:
                report['staged_folders'].append(folder_path)
            continue
        else:
            # lone track of an album we don't have -> behaves like a singleton
            # Apply same collision/duplicate handling as used for album folders
            report['singletons'] += 1
            f = members[0]
            ext = os.path.splitext(f['path'])[1]
            base_name = f"{sanitize(f['artist'])} - {sanitize(f['title'])}{ext}"

            # Check for collisions and disambiguate if needed
            name = base_name
            c = 2
            while os.path.normpath(os.path.join(singles_dir, name)).lower() in seen_singletons:
                name = f"{os.path.splitext(base_name)[0]} ({c}){os.path.splitext(base_name)[1]}"
                c += 1
            seen_singletons.add(os.path.normpath(os.path.join(singles_dir, name)).lower())

            dst = os.path.join(singles_dir, name)
            if os.path.normpath(dst) != os.path.normpath(f['path']):
                singleton_moves.append((f['path'], dst))
            else:
                noop += 1

    return Plan(report, staged_moves, merged_moves, dup_moves, tag_writes, album_tag_writes)