"""lib.catalog.matcher - match a spotify track row against the crate catalog.

ported from playlists/matcher.py during the lib/ refactor: preserves all six
matching tiers exactly (per REFACTOR_PLAN.md, this is one of the two "don't
simplify, just relocate" subsystems in the repo), swapping its own
normalization for lib.text's.

there's no ISRC in the spotify exports, and most of the crate is beat
tapes/bootlegs that won't match MusicBrainz anyway, so matching is by name:
progressively relaxed tiers, first hit wins, each tier guarded tightly enough
that relaxing doesn't start cross-matching unrelated tracks.

catalog entries are lib.tags.read_tags() dicts: {path, artist, albumartist,
album, title, track, length}.

spotify rows are the dicts produced by download.spotify_export /
spotify_manifest.csv: track_name, artist_names (a credit string, "A, B & C"
- not a list), album_name, duration_ms, track_number, track_id. Field access
goes through _row_get() below, which also accepts a few alternate spellings
(title/name, artist/artists, album, length/duration/duration_s) so a
catalog-shaped or hand-built row works too. dict rows and lightweight
namespace/NamedTuple rows both work.

tier order (first hit wins):
  1. exact title + primary-artist token match
  2. exact title + any artist overlap (split_artists on both sides)
  3. exact title + exact album + duration within tolerance
  4. core title (feat. clause stripped from the *local* tag) + artist
     overlap - rescues a local "Title (feat. X)" against a clean spotify
     "Title"
  5. fuzzy title (ratio >= FUZZY_RATIO_THRESHOLD, same leading-4-char
     prefix) + duration within tolerance - hesitant: only fires when there's
     a single unambiguous best candidate above threshold
  6. symbol-only titles (normalize_key() reduces to '', e.g. "$$$") - exact
     raw title first, then falls back to (album, track-number) position;
     both guarded by artist/album/duration so a generic symbol title can't
     cross-match an unrelated track
"""

import collections
import difflib

from lib.text import normalize_key, normalize_title, primary_artist, split_artists, strip_feat_clause

FUZZY_RATIO_THRESHOLD = 0.92
FUZZY_PREFIX_LEN = 4
DURATION_TOLERANCE_SECONDS = 3

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
        return int(n)
    except (TypeError, ValueError):
        return None


def _row_track_id(row):
    return _row_get(row, 'track_id', 'id', 'spotify_id')


# --- duration / artist helpers -----------------------------------------

def _duration_close(a, b, tolerance=DURATION_TOLERANCE_SECONDS):
    if a is None or b is None:
        return False
    return abs(a - b) <= tolerance


def _entry_artist_set(entry):
    raw = entry.get('artist') or entry.get('albumartist') or ''
    return {normalize_key(a) for a in split_artists(raw)}


def _row_artist_set(row):
    return {normalize_key(a) for a in split_artists(_row_artist(row))}


def _artists_overlap(row, entry):
    row_artists = _row_artist_set(row)
    entry_artists = _entry_artist_set(entry)
    if not row_artists or not entry_artists:
        return False
    return bool(row_artists & entry_artists)


def _primary_artist_matches(row, entry):
    row_primary = normalize_key(primary_artist(_row_artist(row)))
    entry_raw = entry.get('artist') or entry.get('albumartist') or ''
    entry_primary = normalize_key(primary_artist(entry_raw))
    return bool(row_primary) and row_primary == entry_primary


class MatchIndex:
    """preprocesses a catalog (list of lib.tags.read_tags() dicts) into the
    lookup groups every tier needs, once per build run, instead of scanning
    the whole catalog per row."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.by_title = collections.defaultdict(list)        # normalize_key(title) -> [entry]
        self.by_prefix = collections.defaultdict(list)        # normalize_key(title)[:4] -> [entry]
        self.by_core_title = collections.defaultdict(list)    # normalize_key(strip_feat_clause(title)) -> [entry]
        self.by_raw_title = collections.defaultdict(list)     # title.strip().lower() -> [entry], for symbol titles
        self.by_album_track = {}                              # (normalize_key(album), track_number) -> entry
        self._build()

    def _build(self):
        for entry in self.catalog:
            title = entry.get('title') or ''
            key = normalize_key(title)
            self.by_title[key].append(entry)
            if key:
                self.by_prefix[key[:FUZZY_PREFIX_LEN]].append(entry)

            core_key = normalize_key(strip_feat_clause(title))
            self.by_core_title[core_key].append(entry)

            raw_key = title.strip().lower()
            self.by_raw_title[raw_key].append(entry)

            album_key = normalize_key(entry.get('album') or '')
            track = entry.get('track') or 0
            if album_key and track:
                # first entry wins on a genuine collision (two tracks
                # sharing (album, track-number) shouldn't happen in a sane
                # crate) - this is only ever a last-resort tier-6 fallback.
                self.by_album_track.setdefault((album_key, track), entry)

    # --- tiers, in order ------------------------------------------------

    def _tier1(self, row, title_key):
        for entry in self.by_title.get(title_key, ()):
            if _primary_artist_matches(row, entry):
                return entry
        return None

    def _tier2(self, row, title_key):
        for entry in self.by_title.get(title_key, ()):
            if _artists_overlap(row, entry):
                return entry
        return None

    def _tier3(self, row, title_key):
        row_album_key = normalize_key(_row_album(row))
        row_duration = _row_duration_seconds(row)
        if not row_album_key:
            return None
        for entry in self.by_title.get(title_key, ()):
            if normalize_key(entry.get('album') or '') != row_album_key:
                continue
            if _duration_close(row_duration, entry.get('length')):
                return entry
        return None

    def _tier4(self, row, title_key):
        # local side already indexed by its own feat.-stripped core title;
        # the spotify title is assumed already clean, so look it up under
        # the same normalize_key() space.
        for entry in self.by_core_title.get(title_key, ()):
            if _artists_overlap(row, entry):
                return entry
        return None

    def _tier5(self, row, title_key):
        if not title_key:
            return None
        row_duration = _row_duration_seconds(row)
        if row_duration is None:
            return None
        prefix = title_key[:FUZZY_PREFIX_LEN]
        candidates = self.by_prefix.get(prefix, ())
        scored = []
        for entry in candidates:
            if not _duration_close(row_duration, entry.get('length')):
                continue
            entry_key = normalize_key(entry.get('title') or '')
            ratio = difflib.SequenceMatcher(None, title_key, entry_key).ratio()
            if ratio >= FUZZY_RATIO_THRESHOLD:
                scored.append((ratio, entry))
        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        # hesitant: only commit if there's a single unambiguous best - a
        # tie at the top means the fuzzy match is genuinely ambiguous and
        # tier 5 should refuse rather than guess.
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return None
        return scored[0][1]

    def _tier6(self, row, title_key):
        if title_key:
            return None  # not a symbol-only title, tier doesn't apply
        row_raw = _row_title(row).strip().lower()
        row_duration = _row_duration_seconds(row)

        def _guarded(entry):
            if _row_album(row) and normalize_key(entry.get('album') or '') != normalize_key(_row_album(row)):
                return False
            if row_duration is not None and entry.get('length') and not _duration_close(row_duration, entry.get('length')):
                return False
            return _artists_overlap(row, entry) or _primary_artist_matches(row, entry)

        for entry in self.by_raw_title.get(row_raw, ()):
            if _guarded(entry):
                return entry

        row_album_key = normalize_key(_row_album(row))
        track_number = _row_track_number(row)
        if row_album_key and track_number:
            entry = self.by_album_track.get((row_album_key, track_number))
            if entry and _guarded(entry):
                return entry
        return None

    def match(self, row):
        """match a single spotify row -> (entry, tier_number) or (None, None)."""
        title_key = normalize_key(_row_title(row))
        for tier_number, tier_fn in (
            (1, self._tier1),
            (2, self._tier2),
            (3, self._tier3),
            (4, self._tier4),
            (5, self._tier5),
            (6, self._tier6),
        ):
            entry = tier_fn(row, title_key)
            if entry is not None:
                return entry, tier_number
        return None, None


def match_rows(rows, catalog=None, index=None):
    """match many spotify rows against the catalog at once.

    pass either `catalog` (a list of lib.tags.read_tags() dicts - a
    MatchIndex is built once internally) or a pre-built `index`
    (lib.catalog.matcher.MatchIndex) if the caller already has one.

    caches by spotify track id, since a track can appear in many playlists
    and should only be resolved once per run.

    returns {'matched': [{'row': row, 'entry': entry, 'tier': int}],
             'unmatched': [row, ...]}
    """
    if index is None:
        if catalog is None:
            raise ValueError("match_rows() needs either `catalog` or `index`")
        index = MatchIndex(catalog)

    cache = {}
    matched = []
    unmatched = []
    for row in rows:
        track_id = _row_track_id(row)
        if track_id is not None and track_id in cache:
            result = cache[track_id]
        else:
            entry, tier = index.match(row)
            result = (entry, tier)
            if track_id is not None:
                cache[track_id] = result
        entry, tier = result
        if entry is None:
            unmatched.append(row)
        else:
            matched.append({'row': row, 'entry': entry, 'tier': tier})
    return {'matched': matched, 'unmatched': unmatched}


def tier_name(tier_number):
    """human-readable label for a tier number, for logging/reports."""
    return _TIER_NAMES.get(tier_number, f'tier_{tier_number}')
