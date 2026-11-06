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

lib/ refactor: the playlist-refcount check now reads a still-staged m3u8 via
lib.m3u.read_m3u8() instead of importing tapedeck.resolve's (now-removed) private
_parse_m3u8 - one fewer duplicate reader of the .m3u8 format.
"""

import os
import shutil

from lib.m3u import read_m3u8   # m3u path-lines -> {track_ids, existing, missing}

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
    """fixed-point bottom-up rmdir of empty dirs under each mirrored subtree,
    up to (not including) the tapedeck root itself. repeats until a full pass
    removes nothing, so a parent that only becomes empty *because* its child
    was just removed in this same pass is re-checked and pruned too."""
    for sub in _PRUNE_SUBS:
        root = os.path.join(tapedeck, sub)
        if not os.path.isdir(root):
            continue
        changed = True
        while changed:
            changed = False
            for dp, dirs, fns in os.walk(root, topdown=False):
                if dp == root:
                    continue
                try:
                    if not dirs and not fns:
                        os.rmdir(dp)
                        changed = True
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
        for ref in read_m3u8(m3u_abs)['existing']:   # existing referenced files
            r = _rel_under(ref, tapedeck)
            if r:
                protected.add(_norm_rel(r))
    return protected


def _norm_rel(rel):
    return os.path.normpath(rel).replace('\\', '/')


def _calculate_protected_files(plan, kind, tapedeck):
    """Calculate which files should be protected from removal.

    For playlist kind, protects audio files that are referenced by remaining
    staged m3u8 files (to prevent removing shared tracks).

    Args:
        plan: List of (src_abs, rel) tuples to be processed
        kind: Type of items ('playlist' or other)
        tapedeck: Path to tapedeck root

    Returns:
        Set of normalized relative paths that should be protected
    """
    def is_m3u8(rel):
        return os.path.splitext(rel)[1].lower() in M3U_EXT

    # playlist refcount: protect audio files a remaining m3u8 still references.
    protected = set()
    if kind == 'playlist':
        removing_m3u8_rels = {_norm_rel(r) for _, r in plan if is_m3u8(r)}
        protected = _remaining_playlist_refs(tapedeck, removing_m3u8_rels)

    return protected


def unstage(items, crate, tapedeck, kind, dry_run=False, verbose=False):
    """remove the tapedeck mirror of each resolved file, pruning empty dirs. for
    kind=='playlist', skip any audio file a still-staged m3u8 also references.
    returns a summary dict {removed, protected, missing, errors, m3u8_removed}."""
    summary = {'removed': 0, 'protected': 0, 'missing': 0, 'errors': 0, 'm3u8_removed': 0}

    plan = _collect(items, crate)

    # Calculate which files should be protected from removal
    protected = _calculate_protected_files(plan, kind, tapedeck)

    for src, rel in plan:
        dst = _dst(src, crate, tapedeck)
        is_audio = not _is_m3u8(rel)
        is_m3u8_rel = _is_m3u8(rel)
        why = ''
        should_protect, reason = _should_protect_item(rel, is_audio, kind, protected)
        if should_protect:
            summary['protected'] += 1
            why = reason
            if dry_run or verbose:
                print(f"  keep  {rel}{why}")
            continue

        # Log the action (for dry-run or verbose)
        mark = 'rm' if os.path.exists(dst) else 'absent'
        if dry_run or verbose:
            print(f"  {mark:<5} {rel}{why}")

        if dry_run:
            _process_dry_run_item(dst, is_m3u8_rel, summary)
            continue

        _process_actual_removal(dst, is_m3u8_rel, summary)

    if not dry_run:
        _prune_empty_dirs(tapedeck)
    return summary


def _is_m3u8(rel):
    """Check if a relative path represents an m3u8 file.

    Args:
        rel: Relative path to check

    Returns:
        True if the path has an m3u8 extension, False otherwise
    """
    return os.path.splitext(rel)[1].lower() in M3U_EXT


def _should_protect_item(rel, is_audio, kind, protected):
    """Check if an item should be protected from removal.

    Args:
        rel: Relative path of the item
        is_audio: Whether the item is an audio file (not m3u8)
        kind: Type of items ('playlist' or other)
        protected: Set of protected relative paths

    Returns:
        Tuple of (should_protect: bool, reason: str)
    """
    if kind == 'playlist' and is_audio and _norm_rel(rel) in protected:
        return True, ' (protected by another playlist)'
    return False, ''


def _process_dry_run_item(dst, is_m3u8_rel, summary):
    """Process an item in dry-run mode.

    Args:
        dst: Destination path
        is_m3u8_rel: Whether the item is an m3u8 file
        summary: Summary dictionary to update
    """
    if os.path.exists(dst):
        summary['m3u8_removed' if is_m3u8_rel else 'removed'] += 1
    else:
        summary['missing'] += 1


def _process_actual_removal(dst, is_m3u8_rel, summary):
    """Process an item for actual removal.

    Args:
        dst: Destination path
        is_m3u8_rel: Whether the item is an m3u8 file
        summary: Summary dictionary to update
    """
    if not os.path.exists(dst):
        summary['missing'] += 1
        return

    try:
        os.remove(dst)
        if is_m3u8_rel:
            summary['m3u8_removed'] += 1
        else:
            summary['removed'] += 1
    except OSError as e:
        summary['errors'] += 1
        print(f"  warning: could not remove {dst}: {e}")
