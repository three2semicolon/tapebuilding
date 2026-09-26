"""organize.cleanup - reorganize the beets crate into proper albums and singles.

repairs the two things the beets two-pass importer gets wrong on this library:
  1. albums split into multiple folders, one per track-artist, because beets
     keyed the album folder on $artist (per-track) instead of $albumartist
     and the source files had no albumartist tag (beets fell back to the
     track artist, which varies on collab/featured tracks).
  2. whole albums scattered as singletons in singles/, because pass 2
     imports every track standalone (no album grouping).

the regrouper works straight off file tags (mediafile), independent of beets:
  - group every audio file in <crate>/albums and <crate>/singles by its album tag
  - >=2 files share an album  -> one album folder, named <albumartist> - <album>
  - exactly 1 file per album   -> singleton in singles/<artist> - <title>
  - no album tag               -> singleton (a file with no album isn't an album)
  - canonical albumartist per group = the dominant artist string across the
    group's files (collab variants "A & B"/"A & C" collapse to "A" when A is
    the majority); fall back to the dominant primary collaborator; else
    "Various Artists" (a true VA compilation like "'SLOWED' EDITS VOL. I").
  - writes the canonical albumartist tag into every album-group file so a
    future beets as-is re-import won't re-split them.
  - skips non-audio files (beets.db, *.log, library.csv, cover art, .nomedia).

grouping is now artist-aware, not just album-title-based: a 2-track
"album" whose canonical_albumartist() only resolves to "Various Artists"
because the two members share zero artist tokens - and neither file's own
albumartist tag actually says Various Artists/VA - is treated as two
unrelated same-titled singles rather than a compilation, and filed as two
singletons instead of one merged folder. This fixes the bug where e.g.
"Anysia Kym - Automatic" and "Spencer. - Automatic" (two different
artists' unrelated singles) collided into one "Various Artists -
Automatic" folder just because they happened to share a title. Larger
(3+ track) no-overlap groups are left to the pre-existing "flag for
manual review" path rather than auto-split - see BUGFIX_PLAN.md's Bug 2
and `is_unrelated_va_collision()` below.

idempotent: re-running on an already-clean crate is a no-op.

this file is now just the regroup-in-place *policy* (grouping, planning,
applying the plan, rebuilding beets.db) - the toolkit half (tag reading,
sanitizing, canonical-albumartist/dominant-album picking, the audio-file
walk, safe_move) moved to lib.tags/lib.text during the lib/ refactor, since
lib.catalog.indexer needed the exact same primitives. organize.preimport
imports those from lib now too, instead of via this file.

cli.py owns argument parsing / exit codes; run_cleanup() below is the plain,
import-safe entry point cli.py (and anything else) calls into.

usage (via organize's cli):
  uv run organize cleanup                        # dry-run: print plan, move nothing
  uv run organize cleanup --apply                # move files + write albumartist tags
  uv run organize cleanup --apply --rebuild-db   # ...then rebuild beets.db from the reorganized crate
  uv run organize cleanup --verbose              # print every planned move
  uv run organize cleanup --crate /path/to/crate
  uv run organize cleanup --resplit              # dry-run: find already-wrongly-merged album
                                                  # folders (predates the Bug 2 fix above) and
                                                  # show how they'd split apart
  uv run organize cleanup --resplit --apply      # actually split them + write fresh tags
"""

import collections
import os
import sys

from lib.paths import resolve as resolve_path
from lib.tags import (
    EXTENSIONS,
    canonical_albumartist,
    dominant_album,
    read_tags,
    safe_move,
    sanitize,
    scan_audio,
    write_tag,
)
from lib.text import normalize_key, split_artists


def resolve_crate(cli_value=None):
    """crate root from --crate, else ARCHIVE_PATH - required, no expanduser
    fallback. deliberately stricter than lib.paths.archive_path()'s default
    (~/music/tapebuilding): this command moves files and rewrites tags, so
    silently landing on a guessed path instead of erroring is the wrong
    failure mode here. same reasoning applies to organize.beets_import's
    crate resolution."""
    return resolve_path('ARCHIVE_PATH', cli_value, required=True)


def _artist_tokens(f):
    """normalized artist-name tokens for one file, unioning artist +
    albumartist so a featured/collab credit on either field counts - same
    union lib.catalog.matcher._entry_artist_set() does for playlist
    matching."""
    tokens = set()
    for field in ('artist', 'albumartist'):
        for a in split_artists(f.get(field) or ''):
            tokens.add(normalize_key(a))
    return tokens


def _is_explicit_va(f):
    """True if this file's own albumartist tag already says Various
    Artists/VA outright - an intentional compilation signal we should
    trust, as opposed to canonical_albumartist() *falling back* to
    'Various Artists' only because a group's artists never agreed on
    anything."""
    return normalize_key(f.get('albumartist') or '') in ('variousartists', 'va')


def shares_artist_token(members):
    """True if at least two members of the group share a normalized
    artist token (artist/albumartist union). False means every member's
    artist set is completely disjoint from every other's - the "two
    unrelated singles that happen to share an album title" pattern Bug 2
    covers, not a genuine multi-artist album or compilation."""
    token_sets = [_artist_tokens(m) for m in members]
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            if token_sets[i] & token_sets[j]:
                return True
    return False


def is_unrelated_va_collision(aa, members):
    """True when canonical_albumartist() resolved a group to 'Various
    Artists' by fallback (no majority, no dominant collaborator) rather
    than because any member's own albumartist tag actually says so, AND
    the group is the narrow case Bug 2 confirmed: exactly two tracks
    whose artist tokens share nothing at all. That combination is almost
    certainly two unrelated same-titled singles, not a compilation -
    default to splitting rather than merging-and-flagging.

    Deliberately scoped to exactly two members. A 3+ track group that
    resolves to 'Various Artists' with no full overlap is left to the
    existing ambiguous-VA flagging path instead of being auto-split -
    that's a genuinely murkier case (could be a real collab album with
    scattered features, could be an accidental collision) that hasn't
    been confirmed to be the same pattern. See BUGFIX_PLAN.md's Bug 2."""
    if aa != 'Various Artists':
        return False
    if any(_is_explicit_va(m) for m in members):
        return False
    if len(members) != 2:
        return False
    return not shares_artist_token(members)


def _raw_artist_tokens(f):
    """artist tokens from ONLY the file's own 'artist' tag - deliberately
    never 'albumartist'. resplit() has to treat an existing folder's
    albumartist tag as untrustworthy: it's the exact field this file's
    own tag-writes set (see build_plan()'s tag_writes / _apply()'s
    write_tag() calls), so a folder that was wrongly merged before the
    Bug 2 fix landed now carries a self-inflicted 'Various Artists'
    albumartist that looks just like a genuine compilation signal. The
    per-track 'artist' tag is never rewritten by this codebase, so it's
    still the real, un-poisoned signal to regroup from."""
    return {normalize_key(a) for a in split_artists(f.get('artist') or '')}


def _artist_components(members):
    """partition members into groups that transitively share at least one
    raw artist token (see _raw_artist_tokens) - a simple union-find over
    pairwise token overlap. members with an artist set disjoint from
    everyone else in the folder end up alone in their own component.
    one component covering every member means the folder is artist-
    coherent as-is; >=2 components means it's a wrong merge to resplit."""
    parent = list(range(len(members)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    token_sets = [_raw_artist_tokens(m) for m in members]
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            if token_sets[i] & token_sets[j]:
                union(i, j)

    components = collections.OrderedDict()
    for i, m in enumerate(members):
        components.setdefault(find(i), []).append(m)
    return list(components.values())


def _scan_folder(folder):
    """audio files directly under an existing album folder, tags read
    fresh off disk (never trusting a cached index) - resplit needs the
    real current 'artist'/'album' tags, not whatever a stale catalog
    might have."""
    members = []
    for dp, dirs, fns in os.walk(folder):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for fn in sorted(fns):
            if os.path.splitext(fn)[1].lower() not in EXTENSIONS:
                continue
            tags = read_tags(os.path.join(dp, fn))
            if tags:
                members.append(tags)
    return members


def _name_album_component(members, existing_names):
    """canonical '<albumartist> - <album>' folder name for one resplit
    component, disambiguated against every folder name already claimed
    this run (existing crate folders + earlier components from this same
    resplit pass) so two components never collide."""
    aa = canonical_albumartist(members)
    album = dominant_album(members)
    name = sanitize(f"{aa} - {album}") or 'Unknown Album'
    base, c = name, 2
    while name in existing_names:
        name = f"{base} ({c})"
        c += 1
    existing_names.add(name)
    return name, aa


def plan_resplit(crate):
    """recompute the artist-aware grouping key for every EXISTING album
    folder under <crate>/albums, from each file's raw 'artist' tag (see
    _raw_artist_tokens for why the folder's current 'albumartist' tag
    can't be trusted for this). A folder whose members split into >=2
    artist-token components (_artist_components) is a Bug-2-style wrong
    merge that predates the grouping-key fix in build_plan() - this is
    what repairs the folders that already exist; build_plan() only stops
    new ones from being created. Folders with a single component (or
    fewer than two files) are left untouched.

    returns (folder_splits, noop_count). folder_splits is a list of
    (old_folder_path, pieces) where each piece is either
    ('single', member, dst_path) or ('album', members, dst_folder, aa)."""
    albums_dir = os.path.join(crate, 'albums')
    singles_dir = os.path.join(crate, 'singles')
    if not os.path.isdir(albums_dir):
        return [], 0

    existing_names = {d for d in os.listdir(albums_dir)
                       if os.path.isdir(os.path.join(albums_dir, d))}
    folder_splits = []
    noop = 0

    for name in sorted(existing_names.copy()):
        folder = os.path.join(albums_dir, name)
        members = _scan_folder(folder)
        if len(members) < 2:
            noop += 1
            continue

        components = _artist_components(members)
        if len(components) == 1:
            noop += 1
            continue

        existing_names.discard(name)  # this folder is going away
        pieces = []
        for comp in components:
            if len(comp) == 1:
                f = comp[0]
                ext = os.path.splitext(f['path'])[1]
                dst = os.path.join(singles_dir,
                                   f"{sanitize(f['artist'])} - {sanitize(f['title'])}{ext}")
                pieces.append(('single', f, dst))
            else:
                new_name, aa = _name_album_component(comp, existing_names)
                pieces.append(('album', comp, os.path.join(albums_dir, new_name), aa))
        folder_splits.append((folder, pieces))

    return folder_splits, noop


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

    all_moves = []  # (src, dst, albumartist_or_None)
    for old_folder, pieces in folder_splits:
        rel = os.path.relpath(old_folder, os.path.join(crate, 'albums'))
        print(f"\n  {rel}/  ->  {len(pieces)} piece(s):")
        for piece in pieces:
            if piece[0] == 'single':
                _kind, f, dst = piece
                all_moves.append((f['path'], dst, None))
                print(f"    1 file  -> singles/{os.path.basename(dst)}")
            else:
                _kind, comp, dst_folder, aa = piece
                seen = set()
                for idx, m in enumerate(comp):
                    ext = os.path.splitext(m['path'])[1]
                    nm = f"{idx + 1:02d} - {sanitize(m['artist'])} - {sanitize(m['title'])}{ext}"
                    base, sfx = os.path.splitext(nm); c = 2
                    while nm.lower() in seen:
                        nm = f"{base} ({c}){sfx}"; c += 1
                    seen.add(nm.lower())
                    all_moves.append((m['path'], os.path.join(dst_folder, nm), aa))
                print(f"    {len(comp)} files -> albums/{os.path.basename(dst_folder)}/  [albumartist={aa!r}]")

    if verbose:
        print("\n  all moves:")
        for src, dst, _aa in all_moves:
            print(f"    {os.path.relpath(src, crate)}  ->  {os.path.relpath(dst, crate)}")

    if not apply:
        print(f"\ndry run - {len(all_moves)} files across {len(folder_splits)} folders would move. "
              "re-run with --apply to do it.")
        return True

    print(f"\nmoving {len(all_moves)} files...")
    for src, dst, _aa in all_moves:
        safe_move(src, dst)
    for old_folder, _pieces in folder_splits:
        try:
            if not os.listdir(old_folder):
                os.rmdir(old_folder)
        except OSError:
            pass

    if not no_tag_write:
        writes = [(dst, aa) for _s, dst, aa in all_moves if aa]
        print(f"writing albumartist tags on {len(writes)} files...")
        for dst, aa in writes:
            write_tag(dst, albumartist=aa)
    else:
        print("(--no-tag-write: albumartist tags left as-is - split folders may re-merge on a future beets run)")

    print("\ndone.")
    print("note: this only moved files on disk - beets.db, the crate catalog, and any")
    print("      local playlists still point at the old paths until you also run:")
    print("        uv run organize cleanup --rebuild-db")
    print("        uv run core sync              # or: playlists --apply --rescrape --reindex")
    return True


def group_files(files):
    """group by normalised album (empty album -> its own single-element bucket so
    it stays a singleton). returns {group_key: [file, ...]} preserving order."""
    groups = collections.OrderedDict()
    for i, f in enumerate(files):
        if f['album']:
            key = ('album', normalize_key(f['album']))
        else:
            key = ('single', i)  # unique per file - never merge missing-album files
        groups.setdefault(key, []).append(f)
    return groups


def build_plan(groups, crate):
    """decide a target path + tag fix for every file.
    returns (album_moves, singleton_moves, noop_count, tag_writes, va_groups,
    split_groups)."""
    albums_dir = os.path.join(crate, 'albums')
    singles_dir = os.path.join(crate, 'singles')

    album_moves = []      # (src, dst, new_albumartist)
    singleton_moves = []  # (src, dst)
    tag_writes = []       # (src, new_albumartist)
    va_groups = []        # (album, track_count, src_skewed_folders)
    split_groups = []     # (album, track_count) - Bug 2: false-VA collisions split apart
    noop = 0

    # de-dup track numbers within a group: prefer the tag's track, else sequence
    def track_label(idx_in_group, f):
        n = f['track'] or (idx_in_group + 1)
        return f"{int(n) if n else idx_in_group+1:02d}"

    for (kind, _), members in groups.items():
        if kind == 'single' or len(members) == 1:
            # singleton: <crate>/singles/<artist> - <title>.ext
            f = members[0]
            ext = os.path.splitext(f['path'])[1]
            dst = os.path.join(singles_dir,
                               f"{sanitize(f['artist'])} - {sanitize(f['title'])}{ext}")
            if os.path.normpath(dst) != os.path.normpath(f['path']):
                singleton_moves.append((f['path'], dst))
            else:
                noop += 1
            continue

        # album group
        aa = canonical_albumartist(members)
        album = dominant_album(members)

        if is_unrelated_va_collision(aa, members):
            # Bug 2: two different artists' singles that happen to share a
            # title collided into one "Various Artists" folder purely
            # because canonical_albumartist() found no majority between
            # them - that's not a compilation, it's two unrelated tracks.
            # File each one as its own singleton instead of merging them.
            split_groups.append((album or 'Unknown Album', len(members)))
            for f in members:
                ext = os.path.splitext(f['path'])[1]
                dst = os.path.join(singles_dir,
                                   f"{sanitize(f['artist'])} - {sanitize(f['title'])}{ext}")
                if os.path.normpath(dst) != os.path.normpath(f['path']):
                    singleton_moves.append((f['path'], dst))
                else:
                    noop += 1
            continue

        folder = sanitize(f"{aa} - {album}") or 'Unknown Album'

        # did we end up at "Various Artists"? flag for the summary
        src_folders = {os.path.basename(os.path.dirname(m['path'])) for m in members}
        if aa == 'Various Artists':
            va_groups.append((album or folder, len(members), sorted(src_folders)))

        # tag writes: enforce the canonical albumartist so future beets runs don't split
        for m in members:
            if normalize_key(m['albumartist'] or '') != normalize_key(aa):
                tag_writes.append((m['path'], aa))

        seen_names = set()
        for idx, m in enumerate(members):
            ext = os.path.splitext(m['path'])[1]
            name = f"{track_label(idx, m)} - {sanitize(m['artist'])} - {sanitize(m['title'])}{ext}"
            # rare filename collision inside the album -> disambiguate
            base, sfx = os.path.splitext(name); c = 2
            while name.lower() in seen_names:
                name = f"{base} ({c}){sfx}"; c += 1
            seen_names.add(name.lower())
            dst = os.path.join(albums_dir, folder, name)
            if os.path.normpath(dst) != os.path.normpath(m['path']):
                album_moves.append((m['path'], dst, aa))
            else:
                noop += 1

    return album_moves, singleton_moves, noop, tag_writes, va_groups, split_groups


def prune_empty_dirs(crate):
    for sub in ('albums', 'singles'):
        root = os.path.join(crate, sub)
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


def rebuild_db(crate, config_path):
    """fresh beets.db matching the reorganized crate: delete the old db, then
    as-is reimport (no autotag, no MusicBrainz lookups) of albums/ and singles/."""
    import subprocess
    db = os.path.join(crate, 'beets.db')
    if os.path.exists(db):
        os.remove(db)
    base = [sys.executable, '-m', 'beets', '--config', config_path,
            '--directory', crate, '--library', db]
    print("\n=== rebuilding beets.db (as-is, no musicbrainz) ===")
    if os.path.isdir(os.path.join(crate, 'albums')):
        print("  importing albums/...")
        subprocess.run(base + ['import', '-A', '-q', os.path.join(crate, 'albums')], check=False)
    if os.path.isdir(os.path.join(crate, 'singles')):
        print("  importing singles/...")
        subprocess.run(base + ['import', '-A', '-q', '-s', os.path.join(crate, 'singles')], check=False)
    print("  done. library.csv will regenerate on the next export.")


def config_path():
    """config.yaml sits alongside this file in organize/."""
    return os.path.join(os.path.dirname(__file__), 'config.yaml')


def run_cleanup(crate=None, apply=False, no_tag_write=False,
                rebuild_db_flag=False, verbose=False):
    """regroup <crate>/albums + <crate>/singles in place. plain, import-safe
    entry point - does its own printing (dry-run plan, then the applied
    summary), same convention as download's export/download functions.
    cli.py resolves args and calls this; no argparse/sys.exit in here."""
    sys.stdout.reconfigure(encoding='utf-8')  # non-ASCII artist names won't crash the console
    sys.stderr.reconfigure(encoding='utf-8')

    crate = resolve_crate(crate)

    print(f"crate : {crate}")
    print(f"mode  : {'apply (files move, tags written)' if apply else 'dry run (nothing moves)'}")
    print()

    files = scan_audio(crate)
    print(f"scanned {len(files)} audio files")
    groups = group_files(files)
    album_moves, singleton_moves, noop, tag_writes, va_groups, split_groups = build_plan(groups, crate)

    album_groups = sum(1 for k, m in groups.items() if k[0] == 'album' and len(m) > 1)
    singleton_count = len(files) - sum(len(m) for k, m in groups.items() if k[0] == 'album' and len(m) > 1)

    print()
    print("=== plan ===")
    print(f"  album groups (>=2 tracks) : {album_groups}")
    print(f"  tracks becoming albums    : {sum(len(m) for k, m in groups.items() if k[0]=='album' and len(m)>1)}")
    print(f"  true singletons           : {singleton_count}")
    print(f"  files moving to albums/   : {len(album_moves)}")
    print(f"  files moving to singles/  : {len(singleton_moves)}")
    print(f"  files already in place     : {noop}")
    print(f"  albumartist tags to write : {0 if no_tag_write else len(tag_writes)}")
    print(f"  'Various Artists' albums  : {len(va_groups)}")
    print(f"  split (false VA collision): {len(split_groups)}")

    if va_groups:
        print("\n  VA albums (no single majority artist -> filed under 'Various Artists'):")
        for album, n, srcs in sorted(va_groups, key=lambda x: -x[1])[:25]:
            print(f"    {n:>4} files  {album!r}  (from {len(srcs)} folder{'s' if len(srcs)!=1 else ''})")

    if split_groups:
        print("\n  split apart (Bug 2 - same-titled but unrelated singles, filed separately"
              " instead of merged as 'Various Artists'):")
        for album, n in sorted(split_groups, key=lambda x: -x[1])[:25]:
            print(f"    {n:>4} files  {album!r}")

    # suspiciously large groups are a wrong-merge smell - list the biggest
    big = sorted(((dominant_album(m), len(m), os.path.basename(os.path.dirname(m[0]['path'])))
                  for k, m in groups.items() if k[0] == 'album' and len(m) > 1),
                 key=lambda x: -x[1])[:15]
    if big:
        print("\n  largest album groups (review for wrong merges - same album name, different real albums):")
        for album, n, cur in big:
            print(f"    {n:>5} files  {album!r}  (now in: {cur})")

    if verbose:
        if album_moves:
            print("\n  album moves:")
            for src, dst, aa in album_moves[:5000]:
                print(f"    {os.path.relpath(src, crate)}  ->  {os.path.relpath(dst, crate)}")
        if singleton_moves:
            print("\n  singleton moves:")
            for src, dst in singleton_moves[:5000]:
                print(f"    {os.path.relpath(src, crate)}  ->  {os.path.relpath(dst, crate)}")

    if not apply:
        print("\ndry run - re-run with --apply to move files and write tags.")
        if tag_writes:
            print(f"(would write albumartist tags on {len(tag_writes)} files; pass --no-tag-write to skip)")
        return True

    if album_moves:
        print(f"\nmoving {len(album_moves)} files into albums/...")
        for src, dst, aa in album_moves:
            safe_move(src, dst)
    if singleton_moves:
        print(f"moving {len(singleton_moves)} files into singles/...")
        for src, dst in singleton_moves:
            safe_move(src, dst)
    prune_empty_dirs(crate)

    if not no_tag_write and tag_writes:
        print(f"writing albumartist tags on {len(tag_writes)} files...")
        # after the move, re-resolve each path: file may have moved to its album folder
        moved = {os.path.normpath(s): d for s, d, _ in album_moves}
        for src, aa in tag_writes:
            path = moved.get(os.path.normpath(src), src)
            write_tag(path, albumartist=aa)
    elif no_tag_write:
        print("(--no-tag-write: albumartist tags left as-is - albums may re-split on a future beets run)")

    print("\ndone.")
    print("note: beets.db now points at old file paths - it's stale until rebuilt.")
    print("      rebuild with:  uv run organize cleanup --rebuild-db")
    print("      (or re-run --apply --rebuild-db next time)")

    if rebuild_db_flag:
        rebuild_db(crate, config_path())

    return True