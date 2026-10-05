"""organize.cleanup.resplit - apply resplit_plan.py's plan: the opt-in
repair pass for album folders that were wrongly merged BEFORE
grouping.py's Bug-2 grouping-key fix landed (unrelated same-titled
singles filed together under 'Various Artists', e.g. two different
artists' "Automatic" singles).

deliberately separate from the regular apply.py/run_cleanup() pass - a
normal `cleanup --apply` run re-groups by album tag every time, but a
folder that was already merged into e.g. 'Various Artists - Automatic'
now carries that albumartist as an on-disk tag, which grouping.py's
forward-looking check treats as an explicit (trustworthy) compilation
signal - so the regular pass alone can't undo historical damage; see
BUGFIX_PLAN.md's cleanup/rebuild section.

usage (via organize's cli):
  uv run organize cleanup --resplit              # dry-run: show the split plan
  uv run organize cleanup --resplit --apply      # actually split + write fresh tags
"""

import os
import sys

from lib.tags import safe_move, write_tag, sanitize

from .common import resolve_crate
from .resplit_plan import plan_resplit


def run_resplit(crate=None, apply=False, no_tag_write=False, verbose=False):
    """opt-in repair pass for album folders that were wrongly merged
    BEFORE the Bug 2 grouping-key fix landed in build_plan(). Recomputes
    every existing album folder's artist components from raw 'artist'
    tags (plan_resplit()) and splits any folder that no longer holds
    together, writing a fresh canonical albumartist tag on each resulting
    piece.

    deliberately separate from run_cleanup()'s regular pass - a normal
    `cleanup --apply` run re-groups by album tag every time, but a
    folder that was already merged into e.g. 'Various Artists - Automatic'
    now carries that albumartist as an on-disk tag, which build_plan()'s
    forward-looking check treats as an explicit (trustworthy) compilation
    signal - so the regular pass alone can't undo historical damage; see
    BUGFIX_PLAN.md's cleanup/rebuild section.

    dry-run by default, like every other command in this repo. doesn't
    rebuild beets.db or the crate catalog itself - follow with
    `cleanup --rebuild-db` and a playlists/tapedeck reindex afterward,
    since this changes file paths."""
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

    crate = resolve_crate(crate)
    print(f"crate : {crate}")
    print(f"mode  : {'apply (files move, tags written)' if apply else 'dry run (nothing moves)'}")
    print()

    folder_splits, noop = plan_resplit(crate)

    print("=== resplit plan ===")
    print(f"  album folders scanned   : {noop + len(folder_splits)}")
    print(f"  folders left as-is      : {noop}")
    print(f"  folders splitting apart : {len(folder_splits)}")

    if not folder_splits:
        print("\nnothing to resplit - every existing album folder is already artist-coherent.")
        return True

    all_moves = []  # (src, dst, albumartist_or_None, album_or_None)
    for old_folder, pieces in folder_splits:
        rel = os.path.relpath(old_folder, os.path.join(crate, 'albums'))
        print(f"\n  {rel}/  ->  {len(pieces)} piece(s):")
        for piece in pieces:
            if piece[0] == 'single':
                _kind, f, dst = piece
                all_moves.append((f['path'], dst, '', ''))
                print(f"    1 file  -> singles/{os.path.basename(dst)}")
            else:
                _kind, comp, dst_folder, (aa, dom_album) = piece
                seen = set()
                for idx, m in enumerate(comp):
                    ext = os.path.splitext(m['path'])[1]
                    nm = f"{idx + 1:02d} - {sanitize(m['artist'])} - {sanitize(m['title'])}{ext}"
                    base, sfx = os.path.splitext(nm); c = 2
                    while nm.lower() in seen:
                        nm = f"{base} ({c}){sfx}"; c += 1
                    seen.add(nm.lower())
                    all_moves.append((m['path'], os.path.join(dst_folder, nm), aa, dom_album))
                print(f"    {len(comp)} files -> albums/{os.path.basename(dst_folder)}/  [albumartist={aa!r}]")

    if verbose:
        print("\n  all moves:")
        for src, dst, _aa, _album in all_moves:
            print(f"    {os.path.relpath(src, crate)}  ->  {os.path.relpath(dst, crate)}")

    if not apply:
        print(f"\ndry run - {len(all_moves)} files across {len(folder_splits)} folders would move. "
              "re-run with --apply to do it.")
        return True

    print(f"\nmoving {len(all_moves)} files...")
    for src, dst, _aa, _album in all_moves:
        safe_move(src, dst)
    for old_folder, _pieces in folder_splits:
        try:
            if not os.listdir(old_folder):
                os.rmdir(old_folder)
        except OSError:
            pass

    if not no_tag_write:
        aa_writes = [(dst, aa) for _s, dst, aa, _album in all_moves if aa is not None]
        album_writes = [(dst, album) for _s, dst, _aa, album in all_moves if album is not None]
        if aa_writes:
            print(f"writing albumartist tags on {len(aa_writes)} files...")
            for dst, aa in aa_writes:
                write_tag(dst, albumartist=aa)
        if album_writes:
            print(f"writing album tags on {len(album_writes)} files...")
            for dst, album in album_writes:
                write_tag(dst, album=album)
    else:
        print("(--no-tag-write: albumartist tags left as-is - split folders may re-merge on a future beets run)")

    print("\ndone.")
    print("note: this only moved files on disk - beets.db, the crate catalog, and any")
    print("      local playlists still point at the old paths until you also run:")
    print("        uv run organize cleanup --rebuild-db")
    print("        uv run core sync              # or: playlists --apply --rescrape --reindex")
    return True


