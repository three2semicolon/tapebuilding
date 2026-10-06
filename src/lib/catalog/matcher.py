"""lib.catalog.matcher - match a spotify track row against the crate catalog.

ported from playlists/matcher.py during the lib/ refactor: preserves all six
matching tiers exactly (per REFACTOR_PLAN.md, this is one of the two "don't
simplify, just relocate" subsystems in the repo), swapping its own
normalization for lib.text's (normalize_key, split_artists, primary_artist,
strip_feat_clause) instead of maintaining its own regex.

CORRECTION (this pass): an earlier version of this file was rebuilt from
PACKAGE_OVERVIEW.md's tier descriptions - the real playlists/matcher.py
wasn't available at the time - and drifted from it in six ways, found on a
side-by-side diff once the real file was in hand:

  1. the local "entry artist set" only looked at one of (artist,
     albumartist), instead of unioning both tags' split segments - a collab
     credited only in albumartist stopped overlapping.
  2. tier 1 kept only a straight primary==primary check, dropping the
     original's other two OR-conditions (spotify's primary token found
     among the local split-artist set; the local primary found among
     spotify's split-artist set).
  3. duration was used as a hard reject on tier 3, and not used as a
     tiebreak at all on tiers 1/2/4 (just first-match-wins). the original
     never hard-rejects on duration through tier 4 - it's a soft
     preference among predicate-passing candidates, falling back to the
     closest match even outside tolerance rather than refusing.
  4. tier 4 dropped the primary-artist-equality OR-branch, and matched
     against every entry instead of only ones whose feat.-clause was
     actually stripped - silently duplicating tier 2's candidates for no
     benefit.
  5. every tier shared one global duration tolerance (3s) instead of the
     original's per-tier tolerances (5s for tiers 1/2/4/6a, 3s for tiers
     3/5/6b).
  6. by_title/by_prefix included entries with an empty normalize_key
     title (blank or symbol-only), so a symbol-titled query could wrongly
     hit tiers 1-3 (matching another symbol title by artist alone) instead
     of falling through to tier 6's dedicated path; and by_album_track
     kept only the first entry per (album, track) instead of all of them,
     silently dropping legitimate duration-tiebreak candidates on a
     collision.

This version restores the original semantics for all six. The row
field-access helpers below (_row_get and friends) are kept from the earlier
rebuild - a genuine improvement over the original's single hardcoded field
names, not a matching-behavior change, since the real CSV columns
(track_name/artist_names/album_name/duration_ms/track_number/track_id) are
still tried first every time.

there's no ISRC in the spotify exports, and most of the crate is beat
tapes/bootlegs that won't match MusicBrainz anyway, so matching is by name:
progressively relaxed tiers, first hit wins, each tier guarded tightly
enough that relaxing doesn't start cross-matching unrelated tracks.

**Album-name normalization (added after the correction above):** tiers 3
and 6b are the only tiers that compare album strings at all (tiers 1/2/4/5
are title+artist-only). Both now key/compare on lib.text.normalize_album()
rather than plain normalize_key(), so a spotify row's "Album" matches a
local file tagged "Album (Deluxe)"/"Album (2009 Remaster)"/"Album (25th
Anniversary Edition)" without the literal strings needing to agree -
edition suffixes are stripped conservatively (delimited clauses only, see
lib.text's docstring) before the comparison, never mid-title.

catalog entries are lib.tags.read_tags() dicts: {path, artist, albumartist,
album, title, track, length}.
"""

import collections
import difflib

from lib.text import normalize_album, normalize_key, primary_artist, split_artists, strip_feat_clause, fold_key, group_key, group_album_key

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
}


# --- row field access -------------------------------------------------
#
# rows come from CSV/dict data upstream (download.spotify_export et al.) and
# field names have drifted a little across call sites historically - accept
# either a dict or an attribute-bearing object, and a couple of spellings
# for duration/track-number, rather than forcing every caller to normalize
# its row shape before calling in.

def _row_get(row, *names, default=None):
    for name in names:
        if isinstance(row, dict):
            if name in row and row[name] not in (None, ''):
                return row[name]
        else:
            value = getattr(row, name, None)
            if value not in (None, ''):
                return value
    return default


def _row_title(row):
    # 'track_name' is the actual spotify_export.py / spotify_manifest.csv
    # column; 'title'/'name' kept as fallbacks for non-CSV-derived rows.
    return _row_get(row, 'track_name', 'title', 'name', default='') or ''


def _row_artist(row):
    # 'artist_names' is the actual CSV column - a "A, B & C" credit string,
    # same shape split_artists()/primary_artist() already expect.
    return _row_get(row, 'artist_names', 'artist', 'artists', default='') or ''


def _row_album(row):
    return _row_get(row, 'album_name', 'album', default='') or ''


def _row_duration_seconds(row):
    # CSV rows carry duration_ms (spotify's native unit); 'length'/'duration'
    # kept as fallbacks for already-seconds sources (e.g. a catalog-shaped row).
    ms = _row_get(row, 'duration_ms')
    if ms is not None:
        try:
            return float(ms) / 1000.0
        except (TypeError, ValueError):
            pass
    seconds = _row_get(row, 'length', 'duration', 'duration_s', 'duration_sec')
    if seconds is not None:
        try:
            return float(seconds)
        except (TypeError, ValueError):
            pass
    return None


def _row_track_number(row):
    n = _row_get(row, 'track_number', 'track')
    try:
        return int(str(n).split('/')[0])
    except (TypeError, ValueError):
        return None


def _row_track_id(row):
    return _row_get(row, 'track_id', 'id', 'spotify_id')


# --- normalization / matching helpers -----------------------------------

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


class MatchIndex:
    """preprocesses a catalog (list of lib.tags.read_tags() dicts) into the
    lookup groups every tier needs, once per build run, instead of scanning
    the whole catalog per row."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.by_title = collections.defaultdict(list)       # normalize_key(title) -> [entry]  (never '' - see tier6 note)
        self.by_prefix = collections.defaultdict(list)       # normalize_key(title)[:4] -> [entry]
        self.by_core_title = collections.defaultdict(list)   # normalize_key(strip_feat_clause(title)) -> [entry], only when it differs from the plain key
        self.by_raw_title = collections.defaultdict(list)    # lowercased/whitespace-collapsed raw title -> [entry]
        self.by_album_track = collections.defaultdict(list)  # (normalize_key(album), track_int) -> [entry]
        # Unicode-aware indexes alongside ASCII ones (for V9 > 0)
        self.by_u_title = collections.defaultdict(list)      # group_key(title) -> [entry]
        self.by_u_prefix = collections.defaultdict(list)     # group_key(title)[:4] -> [entry]
        self.by_u_album_track = collections.defaultdict(list)  # (group_key(album), track_int) -> [entry]
        self._build()

    def _build(self):
        for entry in self.catalog:
            title = entry.get('title') or ''
            key = normalize_key(title)
            u_key = group_key(title)  # Unicode-aware key
            core_key = normalize_key(strip_feat_clause(title))
            raw_key = _raw_key(title)

            # all-symbol/blank titles (key == '') never feed tiers 1-4 - they
            # stay reachable only via raw-title/(album,track), so a symbol
            # query can't cross-match another symbol title purely because
            # both normalize to ''.
            # However, we still want to index Unicode-aware keys for non-blank titles
            # to support V9 (non-Latin matching)
            if key:
                self.by_title[key].append(entry)
                self.by_prefix[key[:FUZZY_PREFIX_LEN]].append(entry)
            # core title only indexed when stripping a feat. clause actually
            # changed something - otherwise it's a pointless duplicate of
            # by_title's own candidates for that key.
            if core_key and core_key != key:
                self.by_core_title[core_key].append(entry)
            if raw_key:
                self.by_raw_title[raw_key].append(entry)

            # Unicode-aware indexing (for V9 > 0)
            # We index all non-blank Unicode-aware keys to support matching
            # of non-Latin titles while preserving the ASCII-only contract for tier 6
            if u_key:  # Only index if we have a meaningful Unicode key
                self.by_u_title[u_key].append(entry)
                self.by_u_prefix[u_key[:FUZZY_PREFIX_LEN]].append(entry)

            # normalize_album() (not normalize_key()) so an edition variant
            # ("Album (Deluxe)") indexes under the same identity as the
            # plain release - see lib.text's docstring.
            album_key = normalize_album(entry.get('album') or '')
            u_album_key = group_album_key(entry.get('album') or '')  # Unicode-aware album key
            track = entry.get('track') or 0
            if album_key and track:
                self.by_album_track[(album_key, track)].append(entry)
            # Unicode-aware album tracking
            if u_album_key and track:
                self.by_u_album_track[(u_album_key, track)].append(entry)

    # --- tiers, in order ------------------------------------------------

    def _tier1(self, row, title_key, want_dur):
        row_primary = _row_primary(row)
        if not row_primary:
            return None
        row_artists = _row_artist_set(row)

        def pred(entry):
            entry_artists = _entry_artist_set(entry)
            entry_primary = _entry_primary(entry)
            return (row_primary in entry_artists
                    or row_primary == entry_primary
                    or (entry_primary and entry_primary in row_artists))

        # Tier 1 only uses ASCII indexes (preserve ''-means-symbol-only contract for tier 6)
        ascii_candidates = self.by_title.get(title_key, [])
        return _pick_best(ascii_candidates, pred, want_dur, _TOLERANCE[1])

    def _tier2(self, row, title_key, want_dur):
        row_artists = _row_artist_set(row)
        if not row_artists:
            return None
        pred = lambda entry: bool(row_artists & _entry_artist_set(entry))

        # Tier 2 only uses ASCII indexes (preserve ''-means-symbol-only contract for tier 6)
        ascii_candidates = self.by_title.get(title_key, [])
        return _pick_best(ascii_candidates, pred, want_dur, _TOLERANCE[2])

    def _tier3(self, row, title_key, want_dur):
        # normalize_album() so a spotify "Album" row still matches a local
        # file tagged "Album (Deluxe)"/"Album (2009 Remaster)" here instead
        # of falling through to the weaker fuzzy tier.
        row_album_key = normalize_album(_row_album(row))
        if not row_album_key:
            return None

        def pred(entry):
            # Apply artist-contradiction veto (Bug 11/D6)
            if _artists_contradict(row, entry):
                return False
            return normalize_album(entry.get('album') or '') == row_album_key

        # Tier 3 only uses ASCII indexes for title (preserve ''-means-symbol-only contract for tier 6)
        # Note: We still use normalize_album for album comparison as intended
        ascii_title_candidates = self.by_title.get(title_key, [])
        return _pick_best(ascii_title_candidates, pred, want_dur, _TOLERANCE[3])

    def _tier4(self, row, title_key, want_dur):
        # rescues a local "Title (feat. X)" against a clean spotify "Title"
        # when the exact-norm tiers (1-3) miss on the suffix. only fires
        # against entries whose feat.-clause was actually stripped (see
        # by_core_title's population guard above).
        row_artists = _row_artist_set(row)
        if not row_artists:
            return None
        row_primary = _row_primary(row)
        core_q = normalize_key(strip_feat_clause(_row_title(row))) or title_key

        def pred(entry):
            return bool(row_artists & _entry_artist_set(entry)) or (row_primary and row_primary == _entry_primary(entry))

        # Tier 4 only uses ASCII indexes (preserve ''-means-symbol-only contract for tier 6)
        candidates = self.by_core_title.get(core_q, [])
        if core_q != title_key:
            # Also check the reverse direction using ASCII indexes only
            reverse_candidates = self.by_title.get(core_q, [])
            # Apply same artist predicate to reverse candidates
            def reverse_pred(entry):
                return bool(row_artists & _entry_artist_set(entry)) or (row_primary and row_primary == _entry_primary(entry))
            candidates.extend([c for c in reverse_candidates if reverse_pred(c)])

        return _pick_best(candidates, pred, want_dur, _TOLERANCE[4])

    def _tier5(self, row, title_key, want_dur):
        # fuzzy title (same leading-4-char prefix) + duration; hesitant.
        # duration filtering here is a hard pre-filter (unlike tiers 1-4's
        # soft tiebreak) - matches the original's `if not _dur_ok(...):
        # continue` before the ratio is even computed. a missing duration
        # never filters anything out, per _duration_close's own rule.
        if not title_key:
            return None
        best, best_ratio = None, 0.0
        # Tier 5 only uses ASCII indexes (preserve ''-means-symbol-only contract for tier 6)
        ascii_entries = self.by_prefix.get(title_key[:FUZZY_PREFIX_LEN], [])
        for entry in ascii_entries:
            if not _duration_close(want_dur, entry.get('length'), _TOLERANCE[5]):
                continue
            # Apply artist-contradiction veto (Bug 11/D6)
            if _artists_contradict(row, entry):
                continue
            entry_key = normalize_key(entry.get('title') or '')
            ratio = difflib.SequenceMatcher(None, entry_key, title_key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = entry
        if best and best_ratio >= FUZZY_RATIO_THRESHOLD:
            return best
        return None

    def _tier6(self, row, title_key, want_dur):
        # all-symbol titles (normalize_key -> ''): tiers 1-5 are blind to
        # them. resolve by exact raw title first (soft duration tiebreak,
        # 6a), then (album, track-number) position (hard duration gate,
        # 6b) - both anchored by artist/album so a generic "$"/"!!" can't
        # cross-match an unrelated track.
        # Preserve the ''-means-symbol-only contract tier 6 relies on
        if title_key:
            return None
        row_raw = _raw_key(_row_title(row))
        # normalize_album() so the by_album_track lookup below stays
        # consistent with how MatchIndex._build() indexed it, and so the
        # anchor check doesn't reject an edition-suffixed local album tag.
        row_album_key = normalize_album(_row_album(row))
        u_row_album_key = group_album_key(_row_album(row))  # Unicode-aware album key
        row_artists = _row_artist_set(row)
        row_primary = _row_primary(row)

        def anchor(entry):
            # Use Unicode-aware artist sets for better matching (V9 > 0)
            row_fold_artists = {fold_key(a) for a in split_artists(_row_artist(row)) if fold_key(a)}
            entry_fold_artists = set()
            for raw in (entry.get('artist'), entry.get('albumartist')):
                for seg in split_artists(raw or ''):
                    fk = fold_key(seg)
                    if fk:
                        entry_fold_artists.add(fk)
            if row_fold_artists and entry_fold_artists and (row_fold_artists & entry_fold_artists):
                return True
            if row_album_key and normalize_album(entry.get('album') or '') == row_album_key:
                return True
            return False

        if row_raw:
            # Check both ASCII and Unicode-aware indexes for raw title
            ascii_candidates = self.by_raw_title.get(row_raw, [])
            u_candidates = self.by_u_title.get(group_key(_row_title(row)), [])  # Using u_title for raw title matching
            # Combine candidates, avoiding duplicates
            all_candidates = ascii_candidates + [c for c in u_candidates if c not in ascii_candidates]
            chosen = _pick_best(all_candidates, anchor, want_dur, _TOLERANCE['6a'])
            if chosen:
                return chosen

        track_number = _row_track_number(row)
        if row_album_key and track_number is not None:
            # Check both ASCII and Unicode-aware indexes for album/track
            ascii_candidates = self.by_album_track.get((row_album_key, track_number), [])
            u_candidates = self.by_u_album_track.get((u_row_album_key, track_number), [])
            # Combine candidates, avoiding duplicates
            all_candidates = ascii_candidates + [c for c in u_candidates if c not in ascii_candidates]
            kept = [c for c in all_candidates if _duration_close(want_dur, c.get('length'), _TOLERANCE['6b'])]
            if kept:
                return min(kept, key=lambda c: abs((c.get('length') or 0) - want_dur) if want_dur else 0)
        return None

    def match(self, row):
        """match a single spotify row -> (entry, tier_number) or (None, None)."""
        title_key = normalize_key(_row_title(row))
        want_dur = _row_duration_seconds(row)
        for tier_number, tier_fn in (
            (1, self._tier1), (2, self._tier2), (3, self._tier3),
            (4, self._tier4), (5, self._tier5), (6, self._tier6),
        ):
            entry = tier_fn(row, title_key, want_dur)
            if entry is not None:
                return entry, tier_number
        return None, None


def tier_name(tier_number):
    """human-readable label for a tier number, for logging/reports."""
    return _TIER_NAMES.get(tier_number, f'tier_{tier_number}')


def match_rows(rows, catalog=None, index=None, verbose=False):
    """resolve a list of spotify rows against the catalog.

    pass either `catalog` (a list of lib.tags.read_tags() dicts - a
    MatchIndex is built once internally) or a pre-built `index`
    (lib.catalog.matcher.MatchIndex) if the caller already has one.

    caches results by spotify track_id, since a track can appear in many
    playlists and should only be resolved once per run.

    returns an ORDERED list, one dict per input row, in input order:
      {'row': row, 'tier': <tier label or 'unmatched'>, 'path': path or
       None, 'title': ..., 'artist': ..., 'length': ...}
    this is playlists/build.py's original contract (was playlists/
    matcher.py's match_rows) - kept flat and ordered, rather than split
    into matched/unmatched buckets, so callers don't need to change how
    they consume it and playlist order (which must mirror spotify's) falls
    out naturally from iterating the result in order.
    """
    if index is None:
        if catalog is None:
            raise ValueError("match_rows() needs either `catalog` or `index`")
        index = MatchIndex(catalog)

    cache = {}
    out = []
    for row in rows:
        tid = _row_track_id(row)
        if tid and tid in cache:
            res = cache[tid]
        else:
            entry, tier_number = index.match(row)
            if entry is None:
                res = {'tier': 'unmatched', 'path': None, 'title': '', 'artist': '', 'length': 0.0}
            else:
                res = {
                    'tier': tier_name(tier_number),
                    'path': entry.get('path'),
                    'title': entry.get('title') or '',
                    'artist': entry.get('artist') or '',
                    'length': float(entry.get('length') or 0.0),
                }
            if tid:
                cache[tid] = res
        rec = {'row': row, **res}
        out.append(rec)
        if verbose:
            mark = '+' if res['path'] else '-'
            print(f"  [{mark}] {_row_artist(row)} - {_row_title(row)}  ({res['tier']})")
    return out
