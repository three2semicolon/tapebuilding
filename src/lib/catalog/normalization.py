"""lib.catalog.normalization - normalization and helper functions for matching.

Extracted from matcher.py to reduce file size and improve organization.
"""

import collections
import difflib
import re

from lib.text import normalize_album, normalize_key, primary_artist, split_artists, strip_feat_clause, fold_key, group_key, group_album_key
from lib.catalog.row_access import _row_artist

FUZZY_RATIO_THRESHOLD = 0.92
FUZZY_PREFIX_LEN = 4

# per-tier duration tolerance, seconds - matches playlists/matcher.py's
# original tol= arguments exactly. NOT a single global constant: tiers
# 1/2/4/6a use 5s, tiers 3/5/6b use 3s.
_TOLERANCE = {1: 5, 2: 5, 3: 3, 4: 5, 5: 3, '6a': 5, '6b': 5}

_TIER_NAMES = {
    1: 'exact_title_primary_artist',
    2: 'exact_title_artist_overlap',
    3: 'exact_title_album_duration',
    4: 'core_title_artist_overlap',
    5: 'fuzzy_title_duration',
    6: 'symbol_title',
    7: 'soundcloud_artist_title',
    8: 'soundcloud_fuzzy_title',
    9: 'soundcloud_title_only',
}


def _raw_key(s):
    """lowercase + collapse internal whitespace, symbols preserved. this is
    the fallback identity for an all-symbol title ("$$$"), whose
    normalize_key() collapses to '' - see tier 6."""
    if not s:
        return ''
    return ' '.join(str(s).lower().split())


def _entry_artist_set(entry):
    """union of split segments from BOTH the artist and albumartist tags -
    a collab credited only in albumartist still overlaps here. matches
    playlists/matcher.py's original `arts` set exactly (it iterates both
    fields and merges every split segment into one set)."""
    names = set()
    for raw in (entry.get('artist'), entry.get('albumartist')):
        for seg in split_artists(raw or ''):
            k = normalize_key(seg)
            if k:
                names.add(k)
    return names


def _entry_primary(entry):
    raw = entry.get('artist') or entry.get('albumartist') or ''
    return normalize_key(primary_artist(raw))


def _row_artist_set(row):
    return {normalize_key(a) for a in split_artists(_row_artist(row)) if normalize_key(a)}


def _row_primary(row):
    return normalize_key(primary_artist(_row_artist(row)))


def _duration_close(want, have, tolerance):
    """missing duration on either side is never a tiebreak veto - matches
    the original have_ok()/_dur_ok()'s explicit 'no data -> ok' rule."""
    if not want or not have:
        return True
    return abs(want - have) <= tolerance


def _artists_contradict(row, entry):
    """Return True only when both sides have a non-empty fold_key artist set
    (split via split_artists; entry set is artist ∪ albumartist) and the two
    sets are completely disjoint. An entry whose artist/albumartist is
    Various Artists or VA contributes no evidence (never contradicts)."""
    # Get row artist set using fold_key
    row_fold_artists = {fold_key(a) for a in split_artists(_row_artist(row)) if fold_key(a)}

    # Get entry artist set using fold_key (artist ∪ albumartist)
    entry_fold_artists = set()
    for raw in (entry.get('artist'), entry.get('albumartist')):
        for seg in split_artists(raw or ''):
            fk = fold_key(seg)
            if fk:
                entry_fold_artists.add(fk)

    # Check if both sets are non-empty and disjoint
    return bool(row_fold_artists and entry_fold_artists and not (row_fold_artists & entry_fold_artists))


def _pick_best(candidates, predicate, want_duration, tolerance):
    """from candidates, keep those passing predicate; duration is a *soft*
    tiebreak among them, never a hard reject - if none of the
    predicate-passing candidates fall within tolerance, still return the
    closest one rather than refusing outright. mirrors the original
    `_pick()`/`have_ok()` exactly (tiers 1-4 and 6a all route through
    this)."""
    kept = [c for c in candidates if predicate(c)]
    if not kept:
        return None
    if want_duration:
        within = [c for c in kept if _duration_close(want_duration, c.get('length'), tolerance)]
        if within:
            kept = within
    return min(kept, key=lambda c: abs((c.get('length') or 0) - want_duration) if want_duration else 0)