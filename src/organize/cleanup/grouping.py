"""organize.cleanup.grouping - the forward-looking regroup pass: decide
where every file in <crate>/albums + <crate>/singles belongs.

  - group every audio file by its album tag (group_files)
  - >=2 files sharing an album -> one album folder, named
    <albumartist> - <album>; canonical albumartist per group is the
    dominant artist string across the group's files (lib.tags.
    canonical_albumartist)
  - exactly 1 file per album, or no album tag -> singleton
  - a group whose members split into disconnected artist components
    (raw `artist` tag only - never albumartist, which this module writes)
    is a same-titled-singles collision unless the compilation guard or
    ambiguity rule says otherwise (resolve_group); components of size 1
    become singletons, size >= 2 stay albums. Fixes e.g. "Anysia Kym - Automatic" and "Spencer. -
    Automatic" colliding into one "Various Artists - Automatic" folder
    just because they share a title. See BUGFIX_PLAN.md's Bug 2.

this module only decides where things go (build_plan()'s returned move
lists); apply.py's run_cleanup() performs the moves/tag-writes and owns
the printed report. resplit.py is the separate, opt-in repair pass for
folders that were already wrongly merged before this module's
grouping-key fix landed - it recomputes from each file's raw 'artist'
tag rather than reusing anything here, since a wrongly-merged folder's
on-disk albumartist tag is exactly what this module's own tag-writes
would have set, so it can't be trusted as an input to a repair pass.
"""

import collections
import os
from dataclasses import dataclass, field
from typing import List, Tuple

from lib.tags import artist_tokens, canonical_albumartist, dominant_album, sanitize, split_group
from lib.text import normalize_album, normalize_key, split_artists, group_key, group_album_key


def _artist_tokens(f):
    """normalized artist-name tokens for one file - RAW `artist` tag only.
    (kept as a name for callers/tests; see lib.tags.artist_tokens for why
    albumartist is excluded: this module writes it, so it's poisoned.)"""
    return artist_tokens(f)


def _is_explicit_va_member(f):
    """True if this file's own albumartist tag says Various Artists/VA."""
    return normalize_key(f.get('albumartist') or '') in ('variousartists', 'va')


# older name, still imported elsewhere
_is_explicit_va = _is_explicit_va_member


def shares_artist_token(members):
    """True if at least two members share an artist token (raw artist only)."""
    if len(members) < 2:
        return False
    token_sets = [_artist_tokens(m) for m in members]
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            if token_sets[i] & token_sets[j]:
                return True
    return False


def is_unrelated_va_collision(members):
    """True when exactly two files share an album key but have completely
    disjoint artists (raw artist tag), and neither carries an explicit
    Various Artists/VA albumartist. Still used by preimport/plan.py; cleanup
    uses resolve_group() below, which handles any group size."""
    if len(members) != 2:
        return False
    if any(_is_explicit_va_member(m) for m in members):
        return False
    return not shares_artist_token(members)


def _group_album_key_of(members):
    keys = [group_album_key(m['album']) for m in members if m['album']]
    if not keys:
        return ''
    return collections.Counter(keys).most_common(1)[0][0]


def _is_self_titled(m, album_key):
    """a single-release row: title == album (edition stripped, unicode-aware)."""
    return bool(album_key) and group_album_key(m['title'] or '') == album_key


def _self_titled_fraction(members):
    if not members:
        return 0.0
    key = _group_album_key_of(members)
    return sum(1 for m in members if _is_self_titled(m, key)) / len(members)


def _self_titled_singles(members):
    """indices of self-titled-single signals: title == album key AND artist
    tokens disjoint from every other member."""
    key = _group_album_key_of(members)
    out = set()
    for i, m in enumerate(members):
        if not _is_self_titled(m, key):
            continue
        others = set()
        for j, o in enumerate(members):
            if i != j:
                others |= _artist_tokens(o)
        if not (_artist_tokens(m) & others):
            out.add(i)
    return out


def _is_compilation_guard(members):
    """never split: a real compilation = >=4 members, >=50% explicit
    Various Artists/VA albumartist, AND titles mostly != album (a pile of
    same-titled singles has title == album on most rows, even when an
    earlier cleanup stamped them all 'Various Artists' - so VA alone is not
    enough to protect a group)."""
    n = len(members)
    if n < 4:
        return False
    va = sum(1 for m in members if _is_explicit_va_member(m))
    return va >= n * 0.5 and _self_titled_fraction(members) < 0.5


def _is_ambiguous_group(members, components):
    """>=4 members, no explicit-VA majority, titles mostly != album, and no
    component holds >=50% of the group: could be an untagged compilation or a
    pile-up. Left merged and reported for manual review."""
    n = len(members)
    if n < 4:
        return False
    va = sum(1 for m in members if _is_explicit_va_member(m))
    if va >= n * 0.5 or _self_titled_fraction(members) >= 0.5:
        return False
    return max(len(c) for c in components) < n * 0.5


def resolve_group(members):
    """decide how one album-keyed group should be treated.
    returns (components, status); status is one of
      'whole'     - one connected component (or <2 members): normal album
      'guarded'   - real compilation, never split
      'ambiguous' - murky >=4 group, kept merged + reported
      'split'     - components should be handled separately
                    (size>=2 -> album, size 1 -> singleton)."""
    if len(members) < 2:
        return [members], 'whole'
    comps = split_group(members)
    if len(comps) == 1:
        return [members], 'whole'
    if _is_compilation_guard(members):
        return [members], 'guarded'
    if _is_ambiguous_group(members, comps):
        return [members], 'ambiguous'
    return comps, 'split'


@dataclass
class Plan:
    """Dataclass for build_plan return value."""
    album_moves: List[Tuple[str, str, str]]  # (src, dst, new_albumartist)
    singleton_moves: List[Tuple[str, str]]   # (src, dst)
    noop_count: int                          # number of files already in place
    tag_writes: List[Tuple[str, str]]        # (src, new_albumartist)
    album_tag_writes: List[Tuple[str, str]]  # (src, new_album)
    va_groups: List[Tuple[str, int, List[str]]]  # (album, track_count, src_skewed_folders)
    split_groups: List[Tuple[str, int]]      # (album, track_count) - false-VA collisions split apart
    ambiguous_groups: List[Tuple[str, int, List[str]]] = field(default_factory=list)  # (album, n, artists)


def group_files(files):
    """group by normalised album identity (empty album -> its own
    single-element bucket so it stays a singleton). Uses
    lib.text.group_album_key() rather than plain normalize_album() so a
    track tagged "Album" and one tagged "Album (Deluxe)"/"Album (2009
    Remaster)" land in the same group instead of forking into two -
    canonical_albumartist()/dominant_album() then pick the folder
    name/tag from whichever raw string is more common across the merged
    group, same majority-vote behavior as any other tag disagreement (no
    new canonical string is invented here - see TODO.md's separate
    apply-time-cleanup item for that). returns {group_key: [file, ...]}
    preserving order."""
    groups = collections.OrderedDict()
    for i, f in enumerate(files):
        if f['album']:
            key = ('album', group_album_key(f['album']))
        else:
            key = ('single', i)  # unique per file - never merge missing-album files
        groups.setdefault(key, []).append(f)
    return groups


def build_plan(groups, crate):
    """decide a target path + tag fix for every file. returns Plan."""
    from lib.text import render_credit

    albums_dir = os.path.join(crate, 'albums')
    singles_dir = os.path.join(crate, 'singles')

    album_moves, singleton_moves = [], []
    tag_writes, album_tag_writes = [], []
    va_groups, split_groups, ambiguous_groups = [], [], []
    noop = 0
    seen_singletons = set()

    def track_label(idx_in_group, f):
        n = f['track'] or (idx_in_group + 1)
        return f"{int(n) if n else idx_in_group + 1:02d}"

    def add_singleton(f):
        nonlocal noop
        ext = os.path.splitext(f['path'])[1]
        base_name = f"{sanitize(f['artist'])} - {sanitize(f['title'])}{ext}"
        name, c = base_name, 2
        while os.path.normpath(os.path.join(singles_dir, name)).lower() in seen_singletons:
            stem, sfx = os.path.splitext(base_name)
            name = f"{stem} ({c}){sfx}"
            c += 1
        seen_singletons.add(os.path.normpath(os.path.join(singles_dir, name)).lower())
        dst = os.path.join(singles_dir, name)
        if os.path.normpath(dst) != os.path.normpath(f['path']):
            singleton_moves.append((f['path'], dst))
        else:
            noop += 1

    def add_album(component, heal_va):
        nonlocal noop
        # in a group we decided to split, an explicit 'Various Artists'
        # albumartist is self-inflicted (an earlier wrong merge), not a signal -
        # ignore it when picking the folder's albumartist, and the tag write
        # below then repairs it.
        basis = [dict(m, albumartist='') if heal_va and _is_explicit_va_member(m) else m
                 for m in component]
        aa = canonical_albumartist(basis)
        album = dominant_album(component)
        folder = sanitize(f"{render_credit(aa)} - {album}") or 'Unknown Album'
        src_folders = {os.path.basename(os.path.dirname(m['path'])) for m in component}
        if aa == 'Various Artists':
            va_groups.append((album or folder, len(component), sorted(src_folders)))
        for m in component:
            if normalize_key(m['albumartist'] or '') != normalize_key(aa):
                tag_writes.append((m['path'], aa))
            if normalize_key(m['album'] or '') != normalize_key(album):
                album_tag_writes.append((m['path'], album))
        seen_names = set()
        for idx, m in enumerate(component):
            ext = os.path.splitext(m['path'])[1]
            name = f"{track_label(idx, m)} - {sanitize(m['artist'])} - {sanitize(m['title'])}{ext}"
            base, sfx = os.path.splitext(name)
            c = 2
            while name.lower() in seen_names:
                name = f"{base} ({c}){sfx}"
                c += 1
            seen_names.add(name.lower())
            dst = os.path.join(albums_dir, folder, name)
            if os.path.normpath(dst) != os.path.normpath(m['path']):
                album_moves.append((m['path'], dst, aa))
            else:
                noop += 1

    for (kind, _), members in groups.items():
        # no album tag / lone track / empty key (Bug 4: never merge on emptiness)
        if kind == 'single' or len(members) == 1 or not (
                members[0]['album'] and group_album_key(members[0]['album'])):
            for f in members:
                add_singleton(f)
            continue

        components, status = resolve_group(members)
        album = dominant_album(members)
        if status == 'split':
            split_groups.append((album, len(members)))
        elif status == 'ambiguous':
            artists = sorted({m['artist'] for m in members})
            ambiguous_groups.append((album, len(members), artists))

        for component in components:
            if len(component) == 1:
                add_singleton(component[0])
            else:
                add_album(component, heal_va=(status == 'split'))

    return Plan(album_moves, singleton_moves, noop, tag_writes, album_tag_writes,
                va_groups, split_groups, ambiguous_groups)
