"""organize.preimport.apply - stage(): the apply half of the preimport
pass. runs plan.py's index_existing_albums()/build_plan() to get the
plan, prints the dry-run/applied report, then performs the moves,
quarantines duplicates, and writes albumartist tags.
"""

import os
import sys

from lib.tags import scan_audio
from organize.cleanup import group_files, resolve_crate
from organize.journal import Journal

from .plan import build_plan, index_existing_albums


def duplicates_dir(crate):
    """quarantine for merge-target tracks the crate already owns in another
    format/source: moved out of <input> so the singles pass can't import them
    as singleton duplicates, but never deleted (recoverable for manual review)."""
    d = os.path.join(crate, 'duplicates')
    os.makedirs(d, exist_ok=True)
    return d




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


def _apply(staged_moves, merged_moves, dup_moves, tag_writes, album_tag_writes,
           no_tag_write, unorganized, crate):
    """perform the moves (stage + merge), quarantine duplicates, then resolve
    moved paths for the tag writes. every move and tag write goes through
    the organize journal (<crate>/.organize_journal.jsonl) so the run can be
    undone with `organize undo`."""
    moved = {}
    quarantined = set()  # normalized *source* paths sent to duplicates/ - no tag writes for these
    with Journal(crate, 'preimport') as j:
        for src, dst, _aa in staged_moves + merged_moves:
            try:
                moved[os.path.normpath(src)] = j.move(src, dst)
            except OSError as e:
                print(f"  move failed: {src} ({e})", file=sys.stderr)

        if dup_moves:
            dest = duplicates_dir(crate)
            for (src,) in dup_moves:
                try:
                    moved[os.path.normpath(src)] = j.move(
                        src, os.path.join(dest, os.path.basename(src)))
                    quarantined.add(os.path.normpath(src))
                except OSError as e:
                    print(f"  dup move failed: {src} ({e})", file=sys.stderr)

        prune_unorganized(unorganized)

        if no_tag_write:
            print("(--no-tag-write: albumartist tags left as-is - beets may still split)")
        else:
            print(f"writing albumartist tags on {len(tag_writes)} files...")
            for src, aa in tag_writes:
                if os.path.normpath(src) in quarantined:
                    continue
                path = moved.get(os.path.normpath(src), src)
                j.tag(path, albumartist=aa)

            if album_tag_writes:
                print(f"writing album tags on {len(album_tag_writes)} files...")
                for src, album in album_tag_writes:
                    if os.path.normpath(src) in quarantined:
                        continue
                    path = moved.get(os.path.normpath(src), src)
                    j.tag(path, album=album)
    print(f"journal: {j.path}  (run {j.run_id}; revert with `organize undo`)")


def stage(unorganized, crate, apply=False, merge_existing=True,
          verbose=False, no_tag_write=False):
    """stage <unorganized> for a clean beets import. returns a report dict;
    beets_import.py reads report['merged_folders'] to flag stale-db merges."""
    sys.stdout.reconfigure(encoding='utf-8')  # non-ASCII artist/album names
    sys.stderr.reconfigure(encoding='utf-8')

    if not os.path.isdir(unorganized):
        print(f"input : {unorganized}  (not found - nothing to stage)")
        return {'staged_folders': [], 'merged_folders': [], 'merged_tracks': 0,
                'singletons': 0, 'tag_writes': 0, 'ambiguous': [], 'scanned': 0,
                'split_groups': []}

    print(f"input : {unorganized}")
    print(f"crate : {crate}")
    print(f"mode  : {'apply (files move, tags written)' if apply else 'dry run (nothing moves)'}")
    print(f"merge : {'existing album folders' if merge_existing else 'new folders only (no merge)'}")
    print()

    files = scan_audio(unorganized, subdirs=None)  # whole-tree walk of <input>
    print(f"scanned {len(files)} audio files")
    groups = group_files(files)
    idx = index_existing_albums(crate) if merge_existing else {}
    report, staged_moves, merged_moves, dup_moves, tag_writes, album_tag_writes = build_plan(
        groups, unorganized, crate, idx)
    report['tag_writes'] = len(tag_writes) if not no_tag_write else 0
    report['album_tag_writes'] = len(album_tag_writes) if not no_tag_write else 0

    album_groups = sum(1 for k, m in groups.items() if k[0] == 'album' and len(m) >= 2)
    print()
    print("=== plan ===")
    print(f"  album groups (>=2 tracks)      : {album_groups}")
    print(f"  staging -> <input>/albums/      : {len(report['staged_folders'])} folders "
          f"({len(staged_moves)} files)")
    print(f"  merging -> existing crate albums: {len(report['merged_folders'])} folders "
          f"({report['merged_tracks']} files)")
    print(f"  singletons (left for pass 2)    : {report['singletons']}")
    print(f"  split (false VA collision)      : {len(report['split_groups'])}")
    print(f"  duplicates (-> crate/duplicates/): {len(report['duplicates'])}")
    print(f"  albumartist tags to write       : {report['tag_writes']}")
    print(f"  album tags to write             : {report['album_tag_writes']}")
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

    if report['split_groups']:
        print("\n  split apart (Bug 2 - same-titled but unrelated singles, left as"
              " singletons instead of staged/merged as 'Various Artists'):")
        for album, n in sorted(report['split_groups'], key=lambda x: -x[1])[:25]:
            print(f"    {n:>4} files  {album!r}")

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
        if tag_writes:
            print(f"(would write albumartist tags on {len(tag_writes)} files; pass --no-tag-write to skip)")
        if album_tag_writes:
            print(f"(would write album tags on {len(album_tag_writes)} files; pass --no-tag-write to skip)")
        return report

    if staged_moves:
        print(f"\nstaging {len(staged_moves)} files into <input>/albums/...")
    if merged_moves:
        print(f"merging {len(merged_moves)} files into existing crate albums...")
    if dup_moves:
        print(f"quarantining {len(dup_moves)} duplicates -> crate/duplicates/...")
    _apply(staged_moves, merged_moves, dup_moves, tag_writes, album_tag_writes, no_tag_write,
           unorganized, crate)

    if report['merged_folders']:
        print("\nmerged tracks are on disk but NOT in beets.db yet. index them with:")
        print("  uv run organize cleanup --rebuild-db")
    print("\ndone.")
    return report