"""organize.cleanup.resplit_plan - the read-only half of the resplit
repair pass: recompute what each existing album folder under
<crate>/albums *should* split into, without moving or tagging anything.
run_resplit() (in resplit.py) applies the plan this module produces.

works straight off each file's raw 'artist' tag rather than trusting
the folder's current 'albumartist' tag - a folder that was wrongly
merged before grouping.py's Bug-2 fix landed now carries a
self-inflicted 'Various Artists' albumartist that looks like a genuine
compilation signal, so the per-track 'artist' tag (never rewritten by
this codebase) is the only trustworthy signal left to regroup from.
"""

import collections
import os

from lib.tags import (
    EXTENSIONS,
    canonical_albumartist,
    dominant_album,
    read_tags,
    sanitize,
)
from lib.text import normalize_key, split_artists, render_credit


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


def _canonical_albumartist_from_artist(members):
    """Like canonical_albumartist but uses ONLY the 'artist' tag, not
    'albumartist'. For resplit, the albumartist tag is untrustworthy
    (it's the self-inflicted 'Various Artists' from the wrong merge).
    Returns the dominant artist string from raw 'artist' tags only."""
    from collections import Counter
    counts = Counter()
    total = 0
    for m in members:
        # Use ONLY the 'artist' tag, split on features/commas
        from lib.text import normalize_key, split_artists
        for a in split_artists(m.get('artist') or ''):
            counts[normalize_key(a)] += 1
            total += 1
    if not counts:
        return 'Various Artists'
    top_token, top_n = counts.most_common(1)[0]
    # 50% threshold: if top token reaches >=50% of total, it's the canonical
    if top_n * 2 >= total:
        # Return the raw (unnormalized) version of the winning token
        for m in members:
            for a in split_artists(m.get('artist') or ''):
                if normalize_key(a) == top_token:
                    return a
    return 'Various Artists'


def _name_album_component(members, existing_names):
    """canonical '<albumartist> - <album>' folder name for one resplit
    component, disambiguated against every folder name already claimed
    this run (existing crate folders + earlier components from this same
    resplit pass) so two components never collide.
    Returns (name, canonical_albumartist, dominant_album)."""
    aa = _canonical_albumartist_from_artist(members)
    album = dominant_album(members)
    name = sanitize(f"{render_credit(aa)} - {album}") or 'Unknown Album'
    base, c = name, 2
    while name in existing_names:
        name = f"{base} ({c})"
        c += 1
    existing_names.add(name)
    return name, aa, album


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
    ('single', member, dst_path) or ('album', members, dst_folder,
    (canonical_albumartist, dominant_album))."""
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
                                   f"{sanitize(render_credit(f['artist']))} - {sanitize(f['title'])}{ext}")
                pieces.append(('single', f, dst))
            else:
                new_name, aa, album = _name_album_component(comp, existing_names)
                pieces.append(('album', comp, os.path.join(albums_dir, new_name), (aa, album)))
        folder_splits.append((folder, pieces))

    return folder_splits, noop


