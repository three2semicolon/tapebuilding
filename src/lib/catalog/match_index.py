"""lib.catalog.match_index - MatchIndex class for efficient catalog matching.

Extracted from matcher.py to reduce file size and improve organization.
"""

import collections
import difflib

from .row_access import (
    _row_title, _row_artist, _row_album, _row_duration_seconds,
    _row_track_number, _row_track_id
)
from .normalization import (
    _raw_key, _entry_artist_set, _entry_primary, _row_artist_set,
    _row_primary, _duration_close, _artists_contradict, _pick_best,
    FUZZY_RATIO_THRESHOLD, FUZZY_PREFIX_LEN, _TIER_NAMES, _TOLERANCE
)
from lib.text import (
    normalize_key, split_artists, strip_feat_clause, fold_key,
    group_key, group_album_key, normalize_album
)
from .soundcloud_helpers import _soundcloud_title_variations, _is_soundcloud_like_title
from .soundcloud_loose import SoundcloudLooseIndex
from .row_access import _row_get


class MatchIndex:
    """preprocesses a catalog (list of lib.tags.read_tags() dicts) into the
    lookup groups every tier needs, once per build run, instead of scanning
    the whole catalog per row."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.by_title = collections.defaultdict(list)       # normalize_key(title) -> [entry]  (never '' - see tier6 note)
        self.by_prefix = collections.defaultdict(list)       # normalize_key(title)[:4] -> [entry]
        self.by_core_title = collections.defaultdict(list)
        # normalize_key(strip_feat_clause(title)) -> [entry], only when it differs from the plain key
        self.by_raw_title = collections.defaultdict(list)    # lowercased/whitespace-collapsed raw title -> [entry]
        self.by_album_track = collections.defaultdict(list)  # (normalize_key(album), track_int) -> [entry]
        # Unicode-aware indexes alongside ASCII ones (for V9 > 0)
        self.by_u_title = collections.defaultdict(list)      # group_key(title) -> [entry]
        self.by_u_prefix = collections.defaultdict(list)     # group_key(title)[:4] -> [entry]
        self.by_u_album_track = collections.defaultdict(list)  # (group_key(album), track_int) -> [entry]
        self._loose = None   # SoundcloudLooseIndex, built lazily on first soundcloud miss
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

    def _get_soundcloud_candidates(self, title_key, title):
        """Get candidate entries for SoundCloud-like titles, using both
        ASCII and Unicode-aware indexes with various matching strategies."""
        candidates = []
        seen_ids = set()

        def add_candidates_from_list(entries):
            for entry in entries:
                # Use path as unique identifier to avoid duplicates
                entry_id = entry.get('path', '')
                if entry_id not in seen_ids:
                    seen_ids.add(entry_id)
                    candidates.append(entry)

        # Always include exact ASCII match (for backward compatibility with Spotify)
        add_candidates_from_list(self.by_title.get(title_key, []))

        # If this looks like SoundCloud data, try additional matching strategies
        if _is_soundcloud_like_title(title):
            # 1. Try Unicode-aware exact match (better for accents)
            u_key = group_key(title)
            if u_key:
                add_candidates_from_list(self.by_u_title.get(u_key, []))

            # 2. Try title variations with ASCII indexes
            for variation in _soundcloud_title_variations(title):
                variation_key = normalize_key(variation)
                if variation_key and variation_key != title_key:
                    add_candidates_from_list(self.by_title.get(variation_key, []))

            # 3. Try title variations with Unicode-aware indexes
            for variation in _soundcloud_title_variations(title):
                variation_u_key = group_key(variation)
                if variation_u_key:
                    add_candidates_from_list(self.by_u_title.get(variation_u_key, []))

        return candidates

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

        # Get candidates - for Spotify: exact match only; for SoundCloud: also try variations
        ascii_candidates = self._get_soundcloud_candidates(title_key, _row_title(row))

        return _pick_best(ascii_candidates, pred, want_dur, _TOLERANCE[1])

    def _tier2(self, row, title_key, want_dur):
        row_artists = _row_artist_set(row)
        if not row_artists:
            return None

        def pred(entry):
            return bool(row_artists & _entry_artist_set(entry))

        # Get candidates - for Spotify: exact match only; for SoundCloud: also try variations
        ascii_candidates = self._get_soundcloud_candidates(title_key, _row_title(row))

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

        # Get candidates - for Spotify: exact match only; for SoundCloud: also try variations
        ascii_title_candidates = self._get_soundcloud_candidates(title_key, _row_title(row))

        result = _pick_best(ascii_title_candidates, pred, want_dur, _TOLERANCE[3])
        # Bug 11/D6: hard duration gate for tier 3 — no "closest anyway" fallback
        # when both durations are known. Tier 3 has no artist check beyond the
        # contradiction veto, so a far-off duration must not match.
        if result and want_dur and not _duration_close(want_dur, result.get('length'), _TOLERANCE[3]):
            return None
        return result

    def _tier4_initial_setup(self, row, title_key):
        """Perform initial setup and validation for _tier4.

        Args:
            row: The row to match against
            title_key: The normalized title key

        Returns:
            tuple: (row_artists, row_primary, core_q) or (None, None, None) if validation fails
        """
        row_artists = _row_artist_set(row)
        if not row_artists:
            return None, None, None
        row_primary = _row_primary(row)
        core_q = normalize_key(strip_feat_clause(_row_title(row))) or title_key
        return row_artists, row_primary, core_q

    def _tier4_create_predicates(self, row_artists, row_primary):
        """Create predicate functions for _tier4.

        Args:
            row_artists: Set of artists from the row
            row_primary: Primary artist from the row

        Returns:
            tuple: (pred, reverse_pred) predicate functions
        """
        def pred(entry):
            return bool(row_artists & _entry_artist_set(entry)) or (row_primary and row_primary == _entry_primary(entry))

        def reverse_pred(entry):
            return bool(row_artists & _entry_artist_set(entry)) or (row_primary and row_primary == _entry_primary(entry))

        return pred, reverse_pred

    def _tier4_get_base_candidates(self, core_q):
        """Get base candidates from by_core_title index.

        Args:
            core_q: The core title query

        Returns:
            list: Base candidates
        """
        return list(self.by_core_title.get(core_q, []))

    def _tier4_get_soundcloud_variations_candidates(self, row_title, core_q):
        """Get candidates from SoundCloud title variations.

        Args:
            row_title: The title from the row
            core_q: The core title query

        Returns:
            list: Candidates from SoundCloud variations
        """
        candidates = []
        if _is_soundcloud_like_title(row_title):
            soundcloud_title = row_title
            for variation in _soundcloud_title_variations(soundcloud_title):
                variation_core = normalize_key(strip_feat_clause(variation))
                if variation_core and variation_core != core_q:
                    candidates.extend(self.by_core_title.get(variation_core, []))
        return candidates

    def _tier4_get_reverse_candidates(self, row, title_key, core_q, row_artists, row_primary):
        """Get reverse direction candidates.

        Args:
            title_key: The normalized title key
            core_q: The core title query
            row_artists: Set of artists from the row
            row_primary: Primary artist from the row

        Returns:
            list: Reverse direction candidates
        """
        reverse_candidates = []
        if core_q != title_key:
            # Also check the reverse direction
            reverse_candidates = list(self.by_title.get(core_q, []))
            # Apply same artist predicate to reverse candidates
            def reverse_pred(entry):
                return bool(row_artists & _entry_artist_set(entry)) or (row_primary and row_primary == _entry_primary(entry))
            reverse_candidates = [entry for entry in reverse_candidates if reverse_pred(entry)]

            # For SoundCloud: also try title variations in reverse direction
            if _is_soundcloud_like_title(_row_title(row)):
                # Generate SoundCloud-friendly title variations
                for variation in _soundcloud_title_variations(_row_title(row)):
                    variation_key = normalize_key(variation)
                    if variation_key and variation_key != title_key:  # Avoid duplicate work
                        reverse_candidates.extend(self.by_title.get(variation_key, []))

        return reverse_candidates

    def _get_unicode_matches_for_key(self, u_key):
        """Get Unicode matches for a given key.

        Args:
            u_key: Unicode key to look up

        Returns:
            list: Matching entries or empty list
        """
        if u_key:
            return self.by_u_title.get(u_key, [])
        return []

    def _get_unicode_matches_for_variations(self, row_title, is_forward):
        """Get Unicode matches for SoundCloud title variations.

        Args:
            row_title: The title from the row
            is_forward: Whether to get forward (True) or reverse (False) candidates

        Returns:
            list: Unicode-aware candidates from variations
        """
        candidates = []
        if _is_soundcloud_like_title(row_title):
            if is_forward:
                for variation in _soundcloud_title_variations(row_title):
                    variation_u_key = group_key(variation)
                    if variation_u_key:
                        candidates.extend(self.by_u_title.get(variation_u_key, []))
            else:
                for variation in _soundcloud_title_variations(row_title):
                    variation_key = normalize_key(variation)
                    if variation_key:
                        variation_core = normalize_key(strip_feat_clause(variation))
                        if variation_core:
                            reverse_u_key_var = group_key(variation_core)
                            if reverse_u_key_var:
                                candidates.extend(self.by_u_title.get(reverse_u_key_var, []))
        return candidates

    def _get_base_unicode_match(self, title_key, core_q, is_forward):
        """Get base Unicode match for title_key or core_q.

        Args:
            title_key: The normalized title key
            core_q: The core title query
            is_forward: Whether to get forward (True) or reverse (False) candidates

        Returns:
            list: Base Unicode-aware candidates
        """
        if is_forward:
            u_key = group_key(title_key)
            return self._get_unicode_matches_for_key(u_key)
        else:
            reverse_u_key = group_key(core_q)
            return self._get_unicode_matches_for_key(reverse_u_key)

    def _tier4_get_unicode_candidates(self, title_key, core_q, row_title, is_forward=True):
        """Get Unicode-aware candidates.

        Args:
            title_key: The normalized title key
            core_q: The core title query
            row_title: The title from the row
            is_forward: Whether to get forward (True) or reverse (False) candidates

        Returns:
            list: Unicode-aware candidates
        """
        candidates = []
        if _is_soundcloud_like_title(row_title):
            # Get base matches
            candidates.extend(self._get_base_unicode_match(title_key, core_q, is_forward))

            # Get matches from variations
            candidates.extend(self._get_unicode_matches_for_variations(row_title, is_forward))

        return candidates

    def _tier4_combine_and_deduplicate(self, candidates, reverse_candidates):
        """Combine all candidates and remove duplicates.

        Args:
            candidates: Forward direction candidates
            reverse_candidates: Reverse direction candidates

        Returns:
            list: Unique candidates
        """
        # Combine all candidates and remove duplicates
        all_candidates = candidates + reverse_candidates
        seen = set()
        unique_candidates = []
        for candidate in all_candidates:
            # Use id as a simple way to deduplicate
            candidate_id = candidate.get('path') or candidate.get('title', '') + str(candidate.get('artist', ''))
            if candidate_id not in seen:
                seen.add(candidate_id)
                unique_candidates.append(candidate)
        return unique_candidates

    def _tier4_select_best_candidate(self, unique_candidates, pred, want_dur):
        """Select the best candidate from unique candidates.

        Args:
            unique_candidates: List of unique candidates
            pred: Predicate function
            want_dur: Whether duration is wanted

        Returns:
            The best matching candidate or None
        """
        return _pick_best(unique_candidates, pred, want_dur, _TOLERANCE[4])

    def _tier4(self, row, title_key, want_dur):
        # rescues a local "Title (feat. X)" against a clean spotify "Title"
        # when the exact-norm tiers (1-3) miss on the suffix. only fires
        # against entries whose feat.-clause was actually stripped (see
        # by_core_title's population guard above).
        # Initial setup
        row_artists, row_primary, core_q = self._tier4_initial_setup(row, title_key)
        if row_artists is None:
            return None

        # Create predicates
        pred, reverse_pred = self._tier4_create_predicates(row_artists, row_primary)

        # Get candidates - for Spotify: exact core title match only; for SoundCloud: also try variations
        candidates = self._tier4_get_base_candidates(core_q)
        candidates.extend(self._tier4_get_soundcloud_variations_candidates(_row_title(row), core_q))

        # Also check the reverse direction (as in original)
        reverse_candidates = self._tier4_get_reverse_candidates(row, title_key, core_q, row_artists, row_primary)

        # Add Unicode-aware candidates for both base and reverse
        candidates.extend(self._tier4_get_unicode_candidates(title_key, core_q, _row_title(row), is_forward=True))
        reverse_candidates.extend(self._tier4_get_unicode_candidates(title_key, core_q, _row_title(row), is_forward=False))

        # Combine all candidates and remove duplicates
        unique_candidates = self._tier4_combine_and_deduplicate(candidates, reverse_candidates)

        # Select best candidate
        return self._tier4_select_best_candidate(unique_candidates, pred, want_dur)

    def _tier5(self, row, title_key, want_dur):
        # fuzzy title (same leading-4-char prefix) + duration; hesitant.
        # duration filtering here is a hard pre-filter (unlike tiers 1-4's
        # soft tiebreak) - matches the original's `if not _dur_ok(...):
        # continue` before the ratio is even computed. a missing duration
        # never filters anything out, per _duration_close's own rule.
        if not title_key:
            return None

        ascii_entries = self._tier5_gather_ascii_entries(row, title_key)
        unique_entries = self._tier5_deduplicate_entries(ascii_entries)
        best, best_ratio = self._tier5_find_best_match(unique_entries, title_key, want_dur, row)

        if best and best_ratio >= FUZZY_RATIO_THRESHOLD:
            return best
        return None

    def _tier5_gather_ascii_entries(self, row, title_key):
        """Gather ASCII entries for tier 5 matching."""
        # For Spotify: ASCII index only
        # For SoundCloud: also consider title variations for prefix matching
        ascii_entries = list(self.by_prefix.get(title_key[:FUZZY_PREFIX_LEN], []))

        # For SoundCloud: also consider variations and Unicode-aware matches
        if _is_soundcloud_like_title(_row_title(row)):
            # Add entries that match the variation's prefix
            for variation in _soundcloud_title_variations(_row_title(row)):
                variation_key = normalize_key(variation)
                if variation_key:
                    ascii_entries.extend(self.by_prefix.get(variation_key[:FUZZY_PREFIX_LEN], []))
            # Also try Unicode-aware prefix matching
            u_key = group_key(_row_title(row))
            if u_key:
                ascii_entries.extend(self.by_u_prefix.get(u_key[:FUZZY_PREFIX_LEN], []))
                for variation in _soundcloud_title_variations(_row_title(row)):
                    variation_u_key = group_key(variation)
                    if variation_u_key:
                        ascii_entries.extend(self.by_u_prefix.get(variation_u_key[:FUZZY_PREFIX_LEN], []))
        return ascii_entries

    def _tier5_deduplicate_entries(self, ascii_entries):
        """Remove duplicates while preserving order."""
        seen = set()
        unique_entries = []
        for entry in ascii_entries:
            # Use id as a simple way to deduplicate
            entry_id = entry.get('path') or entry.get('title', '') + str(entry.get('artist', ''))
            if entry_id not in seen:
                seen.add(entry_id)
                unique_entries.append(entry)
        return unique_entries

    def _tier5_find_best_match(self, unique_entries, title_key, want_dur, row):
        """Find the best match from unique entries."""
        best, best_ratio = None, 0.0
        for entry in unique_entries:
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
        return best, best_ratio

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
        row_album_key = normalize_album(_row_album(row))
        u_row_album_key = group_album_key(_row_album(row))  # Unicode-aware album key

        if row_raw:
            # Check both ASCII and Unicode-aware indexes for raw title
            ascii_candidates = self.by_raw_title.get(row_raw, [])
            u_candidates = self.by_u_title.get(group_key(_row_title(row)), [])  # Using u_title for raw title matching
            # Combine candidates, avoiding duplicates
            all_candidates = ascii_candidates + [c for c in u_candidates if c not in ascii_candidates]
            chosen = self._tier6_process_raw_title_candidates(all_candidates, row, row_album_key, want_dur)
            if chosen:
                return chosen

        track_number = _row_track_number(row)
        if row_album_key and track_number is not None:
            # Check both ASCII and Unicode-aware indexes for album/track
            ascii_candidates = self.by_album_track.get((row_album_key, track_number), [])
            u_candidates = self.by_u_album_track.get((u_row_album_key, track_number), [])
            # Combine candidates, avoiding duplicates
            all_candidates = ascii_candidates + [c for c in u_candidates if c not in ascii_candidates]
            kept = self._tier6_process_album_track_candidates(all_candidates, want_dur)
            if kept:
                return self._tier6_select_best_by_duration(kept, want_dur)
        return None

    def _tier6_process_raw_title_candidates(self, all_candidates, row, row_album_key, want_dur):
        """Process raw title candidates for tier 6."""
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

        chosen = _pick_best(all_candidates, anchor, want_dur, _TOLERANCE['6a'])
        return chosen

    def _tier6_process_album_track_candidates(self, all_candidates, want_dur):
        """Process album/track candidates for tier 6."""
        return [c for c in all_candidates if _duration_close(want_dur, c.get('length'), _TOLERANCE['6b'])]

    def _tier6_select_best_by_duration(self, kept, want_dur):
        """Select the best candidate by duration from kept candidates."""
        return min(kept, key=lambda c: abs((c.get('length') or 0) - want_dur) if want_dur else 0)

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
        # tiers 7-9: SoundCloud-only, only reached after 1-6 all missed, so they
        # can never change an existing (spotify or soundcloud) match.
        if self._is_soundcloud(row):
            if self._loose is None:
                self._loose = SoundcloudLooseIndex(self.catalog)
            entry, tier_number = self._loose.match(row)
            if entry is not None:
                return entry, tier_number
        return None, None

    @staticmethod
    def _is_soundcloud(row):
        # row_access._is_soundcloud_row only recognises https://soundcloud.com/...,
        # which misses the api-v2.soundcloud.com/tracks/<id> rows.
        return 'soundcloud.com/' in str(_row_get(row, 'spotify_url', default='') or '')


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
