"""organize.cleanup.apply - run_cleanup(): the regular regroup-in-place
pass. calls grouping.py's group_files()/build_plan() to decide the
plan, then performs the moves + albumartist tag-writes and prints the
dry-run/applied report. cli.py's `organize cleanup` (no --resplit)
entry point.

every mutating step on the --apply path goes through organize.journal
(<crate>/.organize_journal.jsonl), so a run can be reverted with
`organize undo`. dry-runs never touch the journal.
"""

import glob
import os
import sys
import time
import uuid

from lib.tags import (
    canonical_albumartist,
    dominant_album,
    read_tags,
    scan_audio,
)
from lib.text import group_key, split_artists
from lib import config

from organize.journal import Journal

from .common import resolve_crate
from .grouping import build_plan, group_files

DB_BACKUPS_KEPT = 5


def prune_empty_dirs(crate):
    for sub in ('albums', 'singles'):
        root = os.path.normpath(os.path.join(crate, sub))
        if not os.path.isdir(root):
            continue
        for dp, dirs, fns in os.walk(root, topdown=False):
            dp_norm = os.path.normpath(dp)
            if dp_norm == root:
                continue
            try:
                if not dirs and not fns:
                    os.rmdir(dp)
            except OSError:
                pass


def duplicates_dir(crate):
    """quarantine for true duplicates: moved out of the crate so they don't
    clutter albums/ or get re-suffixed on every run; never deleted, so they
    stay recoverable for manual review."""
    d = os.path.join(crate, 'duplicates')
    os.makedirs(d, exist_ok=True)
    return d


def backup_db(db, keep=DB_BACKUPS_KEPT):
    """move beets.db aside to a timestamped backup instead of deleting it
    (BUGFIX_PLAN.md Bug 15). returns the backup path, or None if there was
    no db. keeps the newest `keep` backups."""
    if not os.path.exists(db):
        return None
    bak = f"{db}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    os.replace(db, bak)
    for old in sorted(glob.glob(db + '.bak-*'))[:-keep]:
        try:
            os.remove(old)
        except OSError:
            pass
    return bak


def rebuild_db(crate, config_path):
    """fresh beets.db matching the reorganized crate: back up (not delete)
    the old db, then as-is reimport (no autotag, no MusicBrainz lookups) of
    albums/ and singles/. if either exit non-zero the backup path is
    printed so the old db can be restored by hand."""
    import subprocess
    db = os.path.join(crate, 'beets.db')
    bak = backup_db(db)
    if bak:
        print(f"\nbacked up existing beets.db -> {bak}")
    base = [sys.executable, '-m', 'beets', '--config', config_path,
            '--directory', crate, '--library', db]
    print("\n=== rebuilding beets.db (as-is, no musicbrainz) ===")
    failed = []
    if os.path.isdir(os.path.join(crate, 'albums')):
        print("  importing albums/...")
        r = subprocess.run(base + ['import', '-A', '-q', os.path.join(crate, 'albums')], check=False)
        if r.returncode != 0:
            failed.append(('albums/', r.returncode))
    if os.path.isdir(os.path.join(crate, 'singles')):
        print("  importing singles/...")
        r = subprocess.run(base + ['import', '-A', '-q', '-s', os.path.join(crate, 'singles')], check=False)
        if r.returncode != 0:
            failed.append(('singles/', r.returncode))
    if failed:
        for what, code in failed:
            print(f"  WARNING: beets import of {what} exited {code}", file=sys.stderr)
        if bak:
            print(f"  the previous db is intact at {bak} - restore it by renaming it back "
                  "to beets.db if this rebuild is incomplete.", file=sys.stderr)
    print("  done. library.csv will regenerate on the next export.")


def config_path():
    """library config path, centralized in lib.config (LIBRARY_CONFIG_PATH)."""
    return config.LIBRARY_CONFIG_PATH


# Known label albumartists that are legitimate for compilations/remix albums
# These are labels that release albums under their own name (e.g. "Monstercat 030")
KNOWN_LABEL_ALBUMARTISTS = {
    'monstercat', 'zephyr', 'daruma', 'joekay', 'joekays',
    'soulection', 'mrsuit', 'chillhop', 'chillhopmusic', 'lofigirl',
    'strangefruits', 'bitbird', 'foreignfamilycollective', 'owsel',
    'gravitas', 'gravitasrecordings', 'wakaan', 'deadbeats', 'neversaydie',
    'disciple', 'disciplerecordings', 'rampage', 'subsidia', 'ophelia',
    'annihilation', 'bassrush', 'insomniac', 'ukf', 'ukfmusic',
    'proximity', 'proximitymusic', 'mrsuicidesheep', 'suicidesheep',
    'tasty', 'tastynetwork', 'ninety9lives', 'nocopyrightsounds', 'ncs',
    'monstercatinstinct', 'monstercatuncaged', 'monstercatsilk', 'kendricklamar',
    'joekay', 'wuxirecordings'
}



def _is_known_label(aa: str) -> bool:
    """Check if albumartist is a known label (case-insensitive, normalized)."""
    return group_key(aa) in KNOWN_LABEL_ALBUMARTISTS


def _is_collaboration(artist: str, albumartist: str) -> bool:
    """True if albumartist appears to be one of the collaborating artists.
    e.g. artist='Skrillex & Fred again..', albumartist='Skrillex' -> True
    Uses group_key token overlap."""
    artist_tokens = {group_key(a) for a in split_artists(artist or '')}
    aa_norm = group_key(albumartist or '')
    return aa_norm in artist_tokens


def check_tags(crate=None, apply=False, verbose=False):
    """scan singles/ and albums/ for albumartist tag anomalies and report
    (with --apply: fix) them. targets two corruption patterns:

      singles/: a file in singles/ carries a non-empty albumartist that is
        neither explicit VA nor its own artist nor a known label nor a
        collaboration partner - the fingerprint of a past wrong merge
        (canonical_albumartist() picked the other artist on a 2-track tie
        and cleanup --apply wrote it; the file went to singles/ but the tag
        stuck). e.g. Diversa - Ego Death.mp3 in singles/ with
        albumartist='The Internet' from a wrong merge with the Internet's
        same-titled album. with --apply, set albumartist to the track's
        own artist (not clear - we always want an albumartist).

      albums/: a file whose albumartist disagrees with the folder's
        canonical albumartist (computed over the folder's members) - a
        straggler tagged by a different album name/artist. with --apply,
        write the canonical value.

    dry-run by default (reports only); plain, import-safe entry point.
    --apply tag writes are journaled (organize.journal)."""
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

    crate = resolve_crate(crate)
    print(f"crate : {crate}")
    print(f"mode  : {'apply (tags written)' if apply else 'dry run (nothing changes)'}")
    print()

    suspicious = []   # (path, kind, current, expected, reason)
    suspicious.extend(_check_singles(crate))
    suspicious.extend(_check_albums(crate))

    _display_suspicious(suspicious, crate, apply)

    if not suspicious:
        print("\nno anomalous albumartist tags found.")
        return {'suspicious': 0, 'fixed': 0}

    if not apply:
        print(f"\ndry run - {len(suspicious)} file(s) would be changed. re-run with --apply to write tags.")
        return {'suspicious': len(suspicious), 'fixed': 0}

    fixed = _apply_fixes(suspicious, crate)
    _display_fixed_results(fixed, suspicious, crate)
    return {'suspicious': len(suspicious), 'fixed': fixed}


def _check_singles(crate):
    """Check singles/ directory for albumartist tag anomalies."""
    suspicious = []
    root = os.path.join(crate, 'singles')
    if not os.path.isdir(root):
        return suspicious

    for dp, dirs, fns in os.walk(root):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        # per-album-folder canonical, computed over that folder's own files
        folder_files = []
        for fn in sorted(fns):
            if fn.lower().endswith(('.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aac')):
                tags = read_tags(os.path.join(dp, fn))
                if tags:
                    folder_files.append(tags)
        for t in folder_files:
            _check_single_file(t, dp, suspicious)
    return suspicious


def _check_single_file(tags, dp, suspicious):
    """Check a single file for albumartist tag anomalies."""
    aa = tags['albumartist'] or ''
    artist = tags['artist'] or ''
    if not aa:
        # no albumartist at all -> should be set to artist
        suspicious.append((os.path.join(dp, tags['path']), 'singles', '(empty)', artist, 'missing'))
        return
    aa_norm = group_key(aa)
    if aa_norm in ('variousartists', 'va'):
        return  # explicit compilation tag - leave alone
    if aa_norm == group_key(artist):
        return  # matches its own artist - fine for a single
    if _is_known_label(aa):
        return  # known label albumartist - legitimate
    if _is_collaboration(artist, aa):
        return  # albumartist is one of the collaborating artists - legitimate
    # True corruption: disjoint albumartist (e.g. Spencer with albumartist=Anysia Kym)
    # Fix: set to the track's own artist
    suspicious.append((os.path.join(dp, tags['path']), 'singles', aa, artist, 'corruption'))


def _check_albums(crate):
    """Check albums/ directory for albumartist tag anomalies."""
    suspicious = []
    root = os.path.join(crate, 'albums')
    if not os.path.isdir(root):
        return suspicious

    for dp, dirs, fns in os.walk(root):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        # per-album-folder canonical, computed over that folder's own files
        folder_files = []
        for fn in sorted(fns):
            if fn.lower().endswith(('.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aac')):
                tags = read_tags(os.path.join(dp, fn))
                if tags:
                    folder_files.append(tags)
        if not folder_files:
            continue
        canonical = canonical_albumartist(folder_files)
        for t in folder_files:
            aa = t['albumartist'] or ''
            if group_key(aa) != group_key(canonical):
                suspicious.append((t['path'], 'albums', aa, canonical, 'mismatch'))
    return suspicious


def _display_suspicious(suspicious, crate, apply):
    """Display suspicious files found during tag checking."""
    print(f"files with anomalous albumartist : {len(suspicious)}")
    for path, kind, cur, exp, reason in suspicious:
        rel = os.path.relpath(path, crate)
        if kind == 'singles':
            if reason == 'missing':
                action = 'set to artist' if apply else 'would set to artist'
            else:  # corruption
                action = f'set to {exp!r}' if apply else f'would set to {exp!r}'
            print(f"  singles/  {rel!r}")
            print(f"    albumartist={cur!r} -> {action} ({reason})")
        else:
            action = 'fix' if apply else 'would fix'
            print(f"  albums/   {rel!r}")
            print(f"    albumartist={cur!r} != canonical {exp!r} -> {action}")


def _apply_fixes(suspicious, crate):
    """Apply fixes for suspicious tags."""
    fixed = 0
    with Journal(crate, 'check-tags') as j:
        for path, kind, cur, exp, reason in suspicious:
            if j.tag(path, albumartist=exp) == 'done':
                fixed += 1
    return fixed


def _display_fixed_results(fixed, suspicious, crate):
    """Display results after applying fixes."""
    print(f"\nwrote {fixed} albumartist tag(s) "
          f"({len(suspicious) - fixed} unchanged/skipped - see the journal for why).")
    # Create a journal instance just to get the path and run_id for reporting
    with Journal(crate, 'check-tags') as j:
        print(f"journal: {j.path}  (run {j.run_id}; revert with `organize undo`)")
    print("note: beets.db may still hold the old tags - rebuild with `uv run organize cleanup --rebuild-db`")
    print("      if you want the library csv/beets.db to match.")


def _setup_run_cleanup(crate=None, apply=False, no_tag_write=False,
                       rebuild_db_flag=False, verbose=False):
    """Setup stdout/stderr encoding and resolve crate."""
    sys.stdout.reconfigure(encoding='utf-8')  # non-ASCII artist names won't crash the console
    sys.stderr.reconfigure(encoding='utf-8')
    return resolve_crate(crate)
    # TEST COMMENT


def _scan_and_preprocess(crate):
    """Scan audio files."""
    files = scan_audio(crate)
    print(f"scanned {len(files)} audio files")
    return files


def _display_plan(album_groups, singleton_count, album_moves, singleton_moves, dup_moves,
                  noop, tag_writes, album_tag_writes, va_groups, split_groups, groups,
                  no_tag_write):
    """Display the cleanup plan."""
    print()
    print("=== plan ===")
    print(f"  album groups (>=2 tracks) : {album_groups}")
    print(f"  tracks becoming albums    : {sum(len(m) for k, m in groups.items() if k[0]=='album' and len(m)>1)}")
    print(f"  true singletons           : {singleton_count}")
    print(f"  files moving to albums/   : {len(album_moves)}")
    print(f"  files moving to singles/  : {len(singleton_moves)}")
    print(f"  duplicates quarantined    : {len(dup_moves)}")
    print(f"  files already in place     : {noop}")
    print(f"  albumartist tags to write : {0 if no_tag_write else len(tag_writes)}")
    print(f"  album tags to write       : {0 if no_tag_write else len(album_tag_writes)}")
    print(f"  title tags to write     : {0 if no_tag_write else len([])}")  # No title tag writes implemented
    print(f"  'Various Artists' albums  : {len(va_groups)}")
    print(f"  split (false VA collision): {len(split_groups)}")
    if split_groups:
        split_albums = sorted({album for album, _, _ in split_groups})
        print(f"  split albums              : {', '.join(split_albums)}")
    # Show largest album groups summary (details in verbose)
    if groups:
        # Find the largest album group(s)
        album_group_lengths = [(dominant_album(m), len(m)) for k, m in groups.items() if k[0] == 'album' and len(m) > 1]
        if album_group_lengths:
            max_length = max(length for _, length in album_group_lengths)
            largest_groups = [album for album, length in album_group_lengths if length == max_length]
            largest_groups_str = ', '.join([f"'{g}'" for g in largest_groups])
            if len(largest_groups) == 1:
                print(f"  largest album groups: {largest_groups_str} ({max_length} tracks)")
            else:
                print(f"  largest album groups: {largest_groups_str} ({max_length} tracks each)")


def _display_verbose_details(verbose, va_groups, split_groups, ambiguous_groups, groups,
                           album_moves, singleton_moves, crate):
    """Display verbose details if requested."""
    if not verbose:
        return

    _display_va_albums(va_groups)
    _display_split_groups(split_groups)
    _display_ambiguous_groups(ambiguous_groups)
    _display_large_album_groups(groups)
    _display_album_moves(album_moves, crate)
    _display_singleton_moves(singleton_moves, crate)


def _display_va_albums(va_groups):
    """Display VA albums in verbose mode."""
    if va_groups:
        print("\n  VA albums (no single majority artist -> filed under 'Various Artists'):")
        for album, n, srcs in sorted(va_groups, key=lambda x: -x[1])[:25]:
            print(f"    {n:>4} files  {album!r}  (from {len(srcs)} folder{'s' if len(srcs)!=1 else ''})")


def _display_split_groups(split_groups):
    """Display split groups in verbose mode."""
    if split_groups:
        print("\n  split apart (Bug 2 - same-titled but unrelated singles, filed separately"
              " instead of merged as 'Various Artists'):")
        for album, n, artists in sorted(split_groups, key=lambda x: -x[1])[:25]:
            print(f"    {n:>4} files  {album!r}  [{', '.join(artists)}]")


def _display_ambiguous_groups(ambiguous_groups):
    """Display ambiguous groups in verbose mode."""
    if ambiguous_groups:
        print("\n  ambiguous groups (>=4 tracks, unclear structure - kept merged for review):")
        for album, n, artists in sorted(ambiguous_groups, key=lambda x: -x[1])[:25]:
            print(f"    {n:>4} files  {album!r}  [{', '.join(artists)}]")


def _display_large_album_groups(groups):
    """Display suspiciously large album groups in verbose mode."""
    # suspiciously large groups are a wrong-merge smell - list the biggest
    big = sorted(((dominant_album(m), len(m), os.path.basename(os.path.dirname(m[0]['path'])))
                  for k, m in groups.items() if k[0] == 'album' and len(m) > 1),
                 key=lambda x: -x[1])[:15]
    if big:
        print("\n  largest album groups (review for wrong merges - same album name, different real albums):")
        for album, n, cur in big:
            print(f"    {n:>5} files  {album!r}  (now in: {cur})")


def _display_album_moves(album_moves, crate):
    """Display album moves in verbose mode."""
    if album_moves:
        print("\n  album moves:")
        for src, dst, aa in album_moves[:5000]:
            print(f"    {os.path.relpath(src, crate)}  ->  {os.path.relpath(dst, crate)}")


def _display_singleton_moves(singleton_moves, crate):
    """Display singleton moves in verbose mode."""
    if singleton_moves:
        print("\n  singleton moves:")
        for src, dst in singleton_moves[:5000]:
            print(f"    {os.path.relpath(src, crate)}  ->  {os.path.relpath(dst, crate)}")


def _handle_dry_run(apply, no_tag_write, tag_writes, album_tag_writes):
    """Handle dry-run mode."""
    if not apply:
        print("\ndry run - re-run with --apply to move files and write tags.")
        if tag_writes:
            print(f"(would write albumartist tags on {len(tag_writes)} files; pass --no-tag-write to skip)")
        if album_tag_writes:
            print(f"(would write album tags on {len(album_tag_writes)} files; pass --no-tag-write to skip)")
        return True


def run_cleanup(crate=None, apply=False, no_tag_write=False,
                rebuild_db_flag=False, verbose=False):
    """regroup <crate>/albums + <crate>/singles in place. plain, import-safe
    entry point - does its own printing (dry-run plan, then the applied
    summary), same convention as download's export/download functions.
    cli.py resolves args and calls this; no argparse/sys.exit in here."""
    crate = _setup_run_cleanup(crate, apply, no_tag_write, rebuild_db_flag, verbose)

    print(f"crate : {crate}")
    print(f"mode  : {'apply (files move, tags written)' if apply else 'dry run (nothing moves)'}")
    print()

    files = _scan_and_preprocess(crate)

    result = _group_and_plan(files, crate)
    groups, plan, album_moves, singleton_moves, dup_moves, noop, tag_writes, \
        album_tag_writes, va_groups, split_groups, ambiguous_groups, album_groups, \
        singleton_count = result

    _display_plan(album_groups, singleton_count, album_moves, singleton_moves, dup_moves,
                  noop, tag_writes, album_tag_writes, va_groups, split_groups, groups,
                  no_tag_write)

    _display_verbose_details(verbose, va_groups, split_groups, ambiguous_groups, groups,
                           album_moves, singleton_moves, crate)

    _handle_dry_run(apply, no_tag_write, tag_writes, album_tag_writes)

    _apply_phase(crate, apply, no_tag_write, tag_writes, album_tag_writes,
                 album_moves, singleton_moves, dup_moves, groups)

    _final_reporting(crate, apply, no_tag_write, tag_writes, album_tag_writes,
                     album_moves, singleton_moves, groups, rebuild_db_flag)


def _apply_phase(crate, apply, no_tag_write, tag_writes, album_tag_writes,
                 album_moves, singleton_moves, dup_moves, groups):
    """Apply the cleanup plan: move files and write tags.

    Fix 7 (two-phase apply): a move whose destination is currently occupied
    by another planned source (a swap or cycle) would collide at apply time
    and spawn fresh `(2)` names. Phase 1 vacates every such destination to a
    temp name first; phase 2 lands the real moves, now collision-free.
    Everything is journaled so the run can be reverted with `organize undo`;
    dry runs never touch the journal."""
    if not apply:
        return
    moved = {}
    temps = {}  # normpath(original src) -> temp path the file now sits at
    quarantined = {os.path.normpath(s) for s, _ in dup_moves}
    with Journal(crate, 'cleanup') as j:
        _vacate_occupied_destinations(j, album_moves, singleton_moves, dup_moves, temps)
        _land_moves(j, album_moves, temps, moved,
                    f"\nmoving {len(album_moves)} files into albums/...")
        _land_moves(j, singleton_moves, temps, moved,
                    f"moving {len(singleton_moves)} files into singles/...")
        _land_moves(j, dup_moves, temps, moved,
                    f"quarantining {len(dup_moves)} duplicate(s) -> {duplicates_dir(crate)}/...")
        prune_empty_dirs(crate)
        if not no_tag_write and tag_writes:
            _apply_tag_writes(j, 'albumartist', tag_writes, quarantined, moved)
        elif no_tag_write:
            print("(--no-tag-write: albumartist tags left as-is - albums may re-split on a future beets run)")
        if not no_tag_write and album_tag_writes:
            _apply_tag_writes(j, 'album', album_tag_writes, quarantined, moved)


def _vacate_occupied_destinations(j, album_moves, singleton_moves, dup_moves, temps):
    """Phase 1 of the two-phase apply: vacate every destination that another
    planned source currently occupies, so swaps and cycles land collision-free
    instead of spawning fresh `(2)` names."""
    all_moves = ([(s, d) for s, d, _ in album_moves]
                 + [(s, d) for s, d in singleton_moves]
                 + [(s, d) for s, d in dup_moves])
    sources = {os.path.normpath(s) for s, _ in all_moves}
    src_index = {os.path.normpath(s): (s, d) for s, d in all_moves}
    vacated = set()
    for src, dst in all_moves:
        sn, dn = os.path.normpath(src), os.path.normpath(dst)
        if dn not in sources or dn == sn or dn in vacated:
            continue
        occupant = src_index.get(dn)
        if not occupant:
            continue
        osrc, odst = occupant
        temp = j.move(osrc, odst + '.phase1-tmp-' + uuid.uuid4().hex[:6])
        temps[os.path.normpath(osrc)] = temp
        vacated.add(dn)


def _land_moves(j, moves, temps, moved, message):
    """Phase 2: land one batch of moves whose destinations are now free."""
    if not moves:
        return
    print(message)
    for src, dst, *_ in moves:
        actual = temps.get(os.path.normpath(src), src)
        moved[os.path.normpath(src)] = j.move(actual, dst)


def _apply_tag_writes(j, field, writes, quarantined, moved):
    """Write one tag field on each non-quarantined file, re-resolving moved
    paths so the tag lands on the file's new location."""
    print(f"writing {field} tags on {len(writes)} files...")
    for src, value in writes:
        if os.path.normpath(src) in quarantined:
            continue
        path = moved.get(os.path.normpath(src), src)
        j.tag(path, **{field: value})


def _final_reporting(crate, apply, no_tag_write, tag_writes, album_tag_writes,
                     album_moves, singleton_moves, groups, rebuild_db_flag):
    """Display final reporting and handle database rebuild."""
    print("\ndone.")
    # Create a journal instance just to get the path and run_id for reporting
    with Journal(crate, 'cleanup') as j:
        print(f"journal: {j.path}  (run {j.run_id}; revert with `uv run organize undo`)")
    print("note: beets.db now points at old file paths - it's stale until rebuilt.")
    print("      rebuild with:  uv run organize cleanup --rebuild-db")
    print("      (or re-run --apply --rebuild-db next time)")

    if rebuild_db_flag:
        rebuild_db(crate, config_path())

    return True


def _test_function():
    """A test function."""
    return 42


def _group_and_plan(files, crate):
    """Group files and build the cleanup plan."""
    groups = group_files(files)
    plan = build_plan(groups, crate)
    album_moves = plan.album_moves
    singleton_moves = plan.singleton_moves
    dup_moves = plan.dup_moves
    noop = plan.noop_count
    tag_writes = plan.tag_writes
    album_tag_writes = plan.album_tag_writes
    va_groups = plan.va_groups
    split_groups = plan.split_groups
    ambiguous_groups = plan.ambiguous_groups

    album_groups = sum(1 for k, m in groups.items() if k[0] == 'album' and len(m) > 1)
    singleton_count = len(files) - sum(len(m) for k, m in groups.items() if k[0] == 'album' and len(m) > 1)

    return (groups, plan, album_moves, singleton_moves, dup_moves, noop, tag_writes,
            album_tag_writes, va_groups, split_groups, ambiguous_groups, album_groups,
            singleton_count)
