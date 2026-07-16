
"""tapedeck/copy - stage (load) and unstage (unload) a mirrored subtree.

the deck mirrors the crate 1:1 by crate-relative path, so every source path maps to
exactly one destination: dst = tapedeck_root / relpath(src, crate). staging copies
files (default) or hardlinks them (--link - same Y: volume saves space), skipping
an existing dst unless --overwrite. folders are expanded to their full subtree
(audio + cover/.pdf siblings) so an album is a complete mirror, not just the audio.

unloading is the inverse: remove the dst for every file the resolved spec would
have staged, then prune the now-empty parent dirs up to the tapedeck root. playlist
unload is refcounted - an audio file is removed only if no *other* m3u8 still in
tapedeck/playlists/ references it, so two playlists sharing a track don't drop it
when one is unloaded.
"""

import os
import shutil

from .resolve import _parse_m3u8   # m3u path-lines -> abs crate files

M3U_EXT = ('.m3u8', '.m3u')
# the mirrored subtrees we prune back up to the tapedeck root on unload
_PRUNE_SUBS = ('albums', 'singles', 'soundtracks', 'playlists')


# --- helpers ----------------------------------------------------------------

def _expand_folder(folder_abs):
    """every file under folder_abs (audio + non-audio siblings) for a full mirror."""
    out = []
    for dp, _, fns in os.walk(folder_abs):
        for fn in fns:
            out.append(os.path.join(dp, fn))
    return out


def _rel_under(src, root):
    """relpath(src, root) if src is inside root, else None (caller skips + warns)."""
    try:
        rel = os.path.relpath(src, root)
    except ValueError:
        return None
    if rel == '..' or rel.startswith('..' + os.sep) or rel.startswith('..' + '/'):
        return None
    return rel


def _dst(src, crate, tapedeck):
    """tapedeck path that mirrors src's crate-relative position."""
    return os.path.normpath(os.path.join(tapedeck, os.path.relpath(src, crate)))


def _collect(items, crate):
    """resolved items -> ordered, de-duped list of (src_abs, rel) to stage/unload.
    folders expand to their subtree; files + m3u8 are passed through; the .m3u8
    itself is staged too (a playlist is its m3u8 + its referenced audio files)."""
    plan = {}            # rel -> src_abs   (rel dedupes across folders/files/m3u8)
    order = []

    def add(src):
        rel = _rel_under(src, crate)
        if rel is None:
            return None
        if rel not in plan:
            plan[rel] = src
            order.append(rel)
        return rel

    for folder in items.get('folders', []):
        for src in _expand_folder(folder):
            add(src)
    for src in items.get('files', []):
        add(src)
    for src in items.get('m3u8', []):
        add(src)
    return [(plan[rel], rel) for rel in order]


def _prune_empty_dirs(tapedeck):
    """bottom-up rmdir of empty dirs under each mirrored subtree, up to (not
    including) the tapedeck root itself."""
    for sub in _PRUNE_SUBS:
        root = os.path.join(tapedeck, sub)
        if not os.path.isdir(root):
            continue
        for dp, dirs, fns in os.walk(root, topdown=False):
            if dp == root:
                continue
            try:
                if not dirs and not fns:
                    os.rmdir(dp)
            except OSError:
                pass


# --- stage (load) -----------------------------------------------------------

def stage(items, crate, tapedeck, mode='copy', overwrite=False, dry_run=False,
          verbose=False):
    """copy/link each resolved file to its tapedeck mirror path. returns a summary
    dict {copied, linked, skipped, overwritten, errors, bytes}."""
    summary = {'copied': 0, 'linked': 0, 'skipped': 0, 'overwritten': 0, 'errors': 0}

    for src, rel in _collect(items, crate):
        dst = _dst(src, crate, tapedeck)
        verb = 'link' if mode == 'link' else 'copy'
        if dry_run or verbose:
            tag = ''
            if os.path.exists(dst):
                tag = ' (exists)' if not overwrite else ' (overwrite)'
            print(f"  {verb:>5}  {rel} -> {dst}{tag}")

        if dry_run:
            if os.path.exists(dst):
                summary['skipped' if not overwrite else 'overwritten'] += 1
            else:
                summary['linked' if mode == 'link' else 'copied'] += 1
            continue

        existed = os.path.exists(dst)
        if existed and not overwrite:
            summary['skipped'] += 1
            continue
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if existed:
                os.remove(dst)
                summary['overwritten'] += 1
            if mode == 'link':
                os.link(src, dst)
                summary['linked'] += 1
            else:
                shutil.copy2(src, dst)
                summary['copied'] += 1
        except OSError as e:
            summary['errors'] += 1
            print(f"  warning: could not {verb} {rel}: {e}")

    return summary


# --- unstage (unload) -------------------------------------------------------

def _remaining_playlist_refs(tapedeck, removing_rels):
    """rel paths (under the tapedeck root) referenced by m3u8s still staged under
    tapedeck/playlists/, excluding the ones being unloaded. protects shared tracks."""
    playlists_dir = os.path.join(tapedeck, 'playlists')
    if not os.path.isdir(playlists_dir):
        return set()
    protected = set()
    for fn in os.listdir(playlists_dir):
        if os.path.splitext(fn)[1].lower() not in M3U_EXT:
            continue
        rel = os.path.join('playlists', fn)
        rel_norm = os.path.normpath(rel)
        if _norm_rel(rel_norm) in removing_rels:
            continue
        m3u_abs = os.path.join(playlists_dir, fn)
        for ref in _parse_m3u8(m3u_abs)[0]:          # existing referenced files
            r = _rel_under(ref, tapedeck)
            if r:
                protected.add(_norm_rel(r))
    return protected


def _norm_rel(rel):
    return os.path.normpath(rel).replace('\\', '/')


def unstage(items, crate, tapedeck, kind, dry_run=False, verbose=False):
    """remove the tapedeck mirror of each resolved file, pruning empty dirs. for
    kind=='playlist', skip any audio file a still-staged m3u8 also references.
    returns a summary dict {removed, protected, missing, errors, m3u8_removed}."""
    summary = {'removed': 0, 'protected': 0, 'missing': 0, 'errors': 0, 'm3u8_removed': 0}

    plan = _collect(items, crate)
    is_m3u8 = lambda rel: os.path.splitext(rel)[1].lower() in M3U_EXT

    # playlist refcount: protect audio files a remaining m3u8 still references.
    protected = set()
    if kind == 'playlist':
        removing_m3u8_rels = {_norm_rel(r) for _, r in plan if is_m3u8(r)}
        protected = _remaining_playlist_refs(tapedeck, removing_m3u8_rels)

    for src, rel in plan:
        dst = _dst(src, crate, tapedeck)
        is_audio = not is_m3u8(rel)
        why = ''
        if kind == 'playlist' and is_audio and _norm_rel(rel) in protected:
            summary['protected'] += 1
            why = ' (protected by another playlist)'
            if dry_run or verbose:
                print(f"  keep  {rel}{why}")
            continue

        if dry_run or verbose:
            mark = 'rm' if os.path.exists(dst) else 'absent'
            print(f"  {mark:<5} {rel}{why}")

        if dry_run:
            if os.path.exists(dst):
                summary['m3u8_removed' if is_m3u8(rel) else 'removed'] += 1
            else:
                summary['missing'] += 1
            continue

        if not os.path.exists(dst):
            summary['missing'] += 1
            continue
        try:
            os.remove(dst)
            if is_m3u8(rel):
                summary['m3u8_removed'] += 1
            else:
                summary['removed'] += 1
        except OSError as e:
            summary['errors'] += 1
            print(f"  warning: could not remove {rel}: {e}")

    if not dry_run:
        _prune_empty_dirs(tapedeck)
    return summary
