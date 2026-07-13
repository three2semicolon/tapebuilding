#!/usr/bin/env python3
"""
preimport.py - stage unorganized/ so the beets importer does the right thing.

runs cleanup.py's regrouping logic BEFORE beets, not after. the two-pass
importer (beets_import.py) splits albums into one folder per track-artist and
leaks whole albums into singles/ because (a) incoming files carry no
albumartist tag, so beets' default album path template keys the folder on the
per-track artist, which varies on collab/featured tracks; and (b) album tracks
dumped loose (not under an albums/ folder) are skipped by the album pass and
swept up as singletons by the singles pass.

this pre-pass fixes both, straight off file tags (mediafile), independent of
beets:

  - scan every audio file under <input> (default <crate>/unorganized).
  - group by album tag. groups of >=2 files that share an album become one
    staged folder <input>/albums/<albumartist> - <album>/, with the canonical
    albumartist written into every file's tag - so beets' $albumartist template
    resolves to one value (one folder, no split) and the album pass sees a real
    folder (no singleton leak).
  - singletons (no album tag, or a lone track of an album we don't have) stay
    loose for the beets singles pass.
  - add to existing albums: if <crate>/albums already holds an album with the
    same (albumartist, album), route the incoming tracks INTO that folder and
    write the existing album's albumartist tag (keep the folder tag-consistent
    so a future as-is reimport won't re-split). merge matching is conservative -
    an incoming group only merges when exactly one existing folder matches the
    normalized (albumartist, album); ambiguous collisions stage a new folder
    instead of risking a wrong merge. merges are filesystem-only; beets.db is
    left stale on the merged tracks until you rebuild it
    (`uv run python -m organize.cleanup --rebuild-db`).

idempotent: re-running on an already-staged drop is a no-op (groups re-stage
to the same folders; already-correct tags aren't rewritten).

beets_import.py runs this automatically before its two passes, so the whole
flow is one command. run preimport standalone to preview/stage without importing:

  uv run python -m organize.preimport                       # dry-run: print plan
  uv run python -m organize.preimport --apply               # stage + write tags
  uv run python -m organize.preimport --apply --verbose     # print every move
  uv run python -m organize.preimport --no-merge-existing   # new folders only
  uv run python -m organize.preimport -i /path -o /crate
"""

import argparse
import os
import sys

from organize.cleanup import (
    EXTENSIONS,
    canonical_albumartist,
    dominant_album,
    group_files,
    norm_key,
    read_tags,
    resolve_crate,
    safe_move,
    sanitize,
    write_albumartist,
)
from organize.cleanup import scan_audio  # generalized to scan_audio(root, subdirs)


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
        albumartist, album = tags[1], tags[2]
        if not album:
            continue
        key = (norm_key(albumartist), norm_key(album))
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
            if t and t[3]:
                titles.add(norm_key(t[3]))
    return titles


def duplicates_dir(crate):
    """quarantine for merge-target tracks the crate already owns in another
    format/source: moved out of <input> so the singles pass can't import them
    as singleton duplicates, but never deleted (recoverable for manual review)."""
    d = os.path.join(crate, 'duplicates')
    os.makedirs(d, exist_ok=True)
    return d


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
        key = (norm_key(aa), norm_key(album))
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
                if norm_key(m['title']) in have:
                    dup_moves.append((m['path'],))
                    report['duplicates'].append(
                        (m['path'], folder_path, m['title']))
                    continue
                dst = os.path.join(folder_path, _member_name(i, m, folder_path, seen))
                if os.path.normpath(dst) != os.path.normpath(m['path']):
                    merged_moves.append((m['path'], dst, aa_for_tag))
                if norm_key(m['albumartist'] or '') != norm_key(aa_for_tag):
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
                if norm_key(m['albumartist'] or '') != norm_key(aa):
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


def prune_unorganized(unorganized):
    """remove now-empty stray dirs left under <input> after moves, but keep the
    input root and the staging albums/ root (even if empty)."""
    staging = os.path.join(unorganized, 'albums')
    for dp, dirs, fns in os.walk(unorganized, topdown=False):
        if dp in (unorganized, staging):
            continue
        if not dirs and not fns:
            try:
                os.rmdir(dp)
            except OSError:
                pass


def _apply(staged_moves, merged_moves, dup_moves, tag_writes, no_tag_write,
           unorganized, crate):
    """perform the moves (stage + merge), quarantine duplicates, then resolve
    moved paths for the tag writes."""
    moved = {}
    for src, dst, _aa in staged_moves + merged_moves:
        try:
            prev = src
            safe_move(src, dst)
            moved[os.path.normpath(prev)] = dst
        except OSError as e:
            print(f"  move failed: {src} ({e})", file=sys.stderr)

    if dup_moves:
        dest = duplicates_dir(crate)
        for (src,) in dup_moves:
            try:
                safe_move(src, os.path.join(dest, os.path.basename(src)))
                moved[os.path.normpath(src)] = dest
            except OSError as e:
                print(f"  dup move failed: {src} ({e})", file=sys.stderr)

    prune_unorganized(unorganized)

    if no_tag_write:
        print("(--no-tag-write: albumartist tags left as-is - beets may still split)")
        return

    print(f"writing albumartist tags on {len(tag_writes)} files...")
    for src, aa in tag_writes:
        path = moved.get(os.path.normpath(src), src)
        write_albumartist(path, aa)


def stage(unorganized, crate, apply=False, merge_existing=True,
          verbose=False, no_tag_write=False):
    """stage <unorganized> for a clean beets import. returns a report dict;
    beets_import.py reads report['merged_folders'] to flag stale-db merges."""
    sys.stdout.reconfigure(encoding='utf-8')  # non-ASCII artist/album names
    sys.stderr.reconfigure(encoding='utf-8')

    if not os.path.isdir(unorganized):
        print(f"input : {unorganized}  (not found - nothing to stage)")
        return {'staged_folders': [], 'merged_folders': [], 'merged_tracks': 0,
                'singletons': 0, 'tag_writes': 0, 'ambiguous': [], 'scanned': 0}

    print(f"input : {unorganized}")
    print(f"crate : {crate}")
    print(f"mode  : {'apply (files move, tags written)' if apply else 'dry run (nothing moves)'}")
    print(f"merge : {'existing album folders' if merge_existing else 'new folders only (no merge)'}")
    print()

    files = scan_audio(unorganized, subdirs=None)  # whole-tree walk of <input>
    print(f"scanned {len(files)} audio files")
    groups = group_files(files)
    idx = index_existing_albums(crate) if merge_existing else {}
    report, staged_moves, merged_moves, dup_moves, tag_writes = build_plan(
        groups, unorganized, crate, idx)
    report['tag_writes'] = len(tag_writes) if not no_tag_write else 0

    album_groups = sum(1 for k, m in groups.items() if k[0] == 'album' and len(m) >= 2)
    print()
    print("=== plan ===")
    print(f"  album groups (>=2 tracks)      : {album_groups}")
    print(f"  staging -> <input>/albums/      : {len(report['staged_folders'])} folders "
          f"({len(staged_moves)} files)")
    print(f"  merging -> existing crate albums: {len(report['merged_folders'])} folders "
          f"({report['merged_tracks']} files)")
    print(f"  singletons (left for pass 2)    : {report['singletons']}")
    print(f"  duplicates (-> crate/duplicates/): {len(report['duplicates'])}")
    print(f"  albumartist tags to write       : {report['tag_writes']}")
    if idx:
        print(f"  existing albums scanned for merge: {len(idx)}")

    if report['duplicates']:
        print("\n  duplicates (crate already has them - quarantined, not merged):")
        for src, folder, title in report['duplicates'][:25]:
            print(f"    {title!r}  <-  {os.path.relpath(src, unorganized)}  "
                  f"(already in {os.path.relpath(folder, crate)})")

    if report['ambiguous']:
        print("\n  ambiguous merges (multiple existing folders match - staged as new):")
        for _aa, album in report['ambiguous'][:25]:
            print(f"    {album!r}")

    if verbose:
        if staged_moves:
            print("\n  staging moves:")
            for src, dst, _aa in staged_moves[:5000]:
                print(f"    {os.path.relpath(src, unorganized)}  ->  "
                      f"{os.path.relpath(dst, unorganized)}")
        if merged_moves:
            print("\n  merge moves:")
            for src, dst, aa in merged_moves[:5000]:
                print(f"    {os.path.relpath(src, unorganized)}  ->  "
                      f"{os.path.relpath(dst, crate)}  [albumartist={aa!r}]")

    if report['merged_folders']:
        print("\n  merges into existing crate albums:")
        for f in sorted(set(report['merged_folders'])):
            print(f"    {os.path.relpath(f, crate)}")

    if not apply:
        print("\ndry run - re-run with --apply to stage folders and write tags.")
        return report

    if staged_moves:
        print(f"\nstaging {len(staged_moves)} files into <input>/albums/...")
    if merged_moves:
        print(f"merging {len(merged_moves)} files into existing crate albums...")
    if dup_moves:
        print(f"quarantining {len(dup_moves)} duplicates -> crate/duplicates/...")
    _apply(staged_moves, merged_moves, dup_moves, tag_writes, no_tag_write,
           unorganized, crate)

    if report['merged_folders']:
        print("\nmerged tracks are on disk but NOT in beets.db yet. index them with:")
        print("  uv run python -m organize.cleanup --rebuild-db")
    print("\ndone.")
    return report


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        description='stage unorganized/ for a clean beets import')
    parser.add_argument('-i', '--input', type=str,
                        help='unorganized root (default: <crate>/unorganized)')
    parser.add_argument('-o', '--crate', '--output', dest='crate', type=str,
                        help='crate root (default: ARCHIVE_PATH in .env)')
    parser.add_argument('--apply', action='store_true',
                        help='stage folders + write tags (default: dry-run)')
    parser.add_argument('--no-merge-existing', action='store_true',
                        help="don't merge incoming tracks into existing crate album folders")
    parser.add_argument('--no-tag-write', action='store_true',
                        help='with --apply: do not rewrite albumartist tags')
    parser.add_argument('--verbose', action='store_true',
                        help='print every planned move')
    args = parser.parse_args()

    crate = resolve_crate(args.crate)
    if not crate:
        sys.exit("error: --crate or ARCHIVE_PATH in .env required")

    input_dir = args.input or os.path.join(crate, 'unorganized')
    if not os.path.isdir(input_dir):
        sys.exit(f"error: input directory not found: {input_dir}")

    stage(input_dir, crate, apply=args.apply,
          merge_existing=not args.no_merge_existing,
          verbose=args.verbose, no_tag_write=args.no_tag_write)


if __name__ == '__main__':
    main()
