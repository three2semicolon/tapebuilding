
"""matcher - map a spotify track row to a local file via progressive relaxation.

no ISRC is available in the exports and the library is mostly beat tapes/bootlegs
(beets config sets `quiet_fallback: asis`), so ISRC matching isn't viable - we
match by name: title first, then artist/album/duration guards. the normalization
mirrors `organize.cleanup.norm_key` (lowercase alphanumeric-only) and
`download.spotify_utils._fuzzy_key` (primary artist + title).

tiers (first hit wins):
  1. exact norm(title) + primary-artist token match          (duration ±5s tiebreak)
  2. exact norm(title) + any artist overlap                  (duration ±5s tiebreak)
  3. exact norm(title) + exact norm(album) + duration ±3s
  4. core title (feat. credit stripped) + artist overlap    (±5s tiebreak)
  5. fuzzy title (ratio >= 0.92, same 4-char prefix) + duration ±3s   (hesitant)
  6. all-symbol titles (norm(title) == "", e.g. "$$$"): exact raw title +
     artist/album, then (album, track-number) position          (±5s)

tier 4 only fires after tiers 1-3 (exact norm title) miss - typically because the
local tag kept a "(feat. ...)" credit the spotify title lacks (e.g. "U Know
What's Up (feat. Lisa ...)"). it strips one featuring parenthetical off the
local title, re-keys the index on that core title, and matches it against the
spotify title with an artist-overlap gate (so a different song that merely
shares a feat-stripped name can't bind).

tier 6 only fires when norm_key collapses the title to "" - every alpha/digit
stripped, nothing for tiers 1-5 to see. it keeps the file in the index under its
raw title and its (album, track) so symbol-only rows still resolve. artist,
album, and duration all guard it so a generic "$" or "!!" can't cross-match an
unrelated crate track.

unresolved rows go to the unmatched log; the same spotify track appears across
many playlists, so results are cached by track_id and resolved once per run.
"""

import difflib
import re

from organize.cleanup import norm_key

_ARTIST_SPLIT = re.compile(r'\s*(?:,|&|/| x | vs | feat\.?|ft\.?|featuring)\s*', flags=re.IGNORECASE)


def _split_artists(s):
    """split a credit string on solo/feat separators -> list of stripped names."""
    if not s:
        return []
    parts = [p.strip() for p in _ARTIST_SPLIT.split(s) if p and p.strip()]
    return [p for p in parts if p]


def _primary_artist(s):
    parts = _split_artists(s)
    return parts[0] if parts else ''


def _prefix(s, n=4):
    return s[:n] if len(s) >= n else s


def _raw_key(s):
    """lowercase + collapse internal whitespace, symbols preserved. norm_key
    strips every non-alphanumeric, so an all-symbol title ("$$$") collapses to
    ""; the raw key is the fallback identity for those (see tier 5)."""
    if not s:
        return ''
    return ' '.join(str(s).lower().split())


# strip one featuring parenthetical from a title: "(feat. X)", "[ft. X]",
# "(with X)", "(vs X)", "(featuring X)". conservative - only an explicit
# featuring marker, never an arbitrary trailing "(Remix)"/"(Radio Edit)", so two
# songs differing by remix don't collapse onto the same core key.
_FEAT_PAREN = re.compile(
    r'\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring|with|vs\.?)\b[^)\]]*[\)\]]\s*',
    flags=re.IGNORECASE)


def _core_title(s):
    """title with featuring parentheticals removed, then whitespace-collapsed.
    'U Know What's Up (feat. Lisa ...)' -> "U Know What's Up"."""
    if not s:
        return ''
    return ' '.join(_FEAT_PAREN.sub(' ', str(s)).split())


def _track_int(v):
    """track number, or the 'n/total' mediafile form, -> int or None."""
    if v is None or v == '':
        return None
    try:
        return int(str(v).split('/')[0])
    except (TypeError, ValueError):
        return None


class MatchIndex:
    """preprocessed local catalog with title + 4-char-prefix lookups."""

    def __init__(self, index):
        self.title_groups = {}        # norm_title -> [proc...]   (empty for all-symbol)
        self.prefix_groups = {}       # norm_title[:4] -> [proc...]
        self.core_groups = {}         # norm(core_title) (feat. stripped) -> [proc...]
        self.raw_groups = {}          # raw_title (symbols kept) -> [proc...]  (all-symbol)
        self.albumtrack_groups = {}   # (norm(album), track_int) -> [proc...]
        for e in index:
            title = e.get('title') or ''
            nt = norm_key(title)
            core_nt = norm_key(_core_title(title))
            raw = _raw_key(title)
            arts = set()
            for a in (e.get('artist'), e.get('albumartist')):
                for seg in _split_artists(a):
                    k = norm_key(seg)
                    if k:
                        arts.add(k)
            na_local = norm_key(e.get('album') or '')
            track_int = _track_int(e.get('track'))
            proc = {
                'e': e,
                'nt': nt,
                'core': core_nt,
                'raw': raw,
                'album': na_local,
                'track': track_int,
                'artists': arts,
                'primary': norm_key(_primary_artist(e.get('artist') or e.get('albumartist') or '')),
                'length': float(e.get('length') or 0.0),
            }
            # all-symbol titles (norm_key -> "") can't feed tiers 1-4, but stay
            # findable under their raw title and (album, track) so tier 6 can
            # reach them. never skip the file entirely on an empty norm title.
            if nt:
                self.title_groups.setdefault(nt, []).append(proc)
                self.prefix_groups.setdefault(_prefix(nt), []).append(proc)
            # core title differs from nt only when a feat. parenthetical was
            # stripped; index those so tier 4 can match the clean spotify title.
            if core_nt and core_nt != nt:
                self.core_groups.setdefault(core_nt, []).append(proc)
            if raw:
                self.raw_groups.setdefault(raw, []).append(proc)
            if na_local and track_int is not None:
                self.albumtrack_groups.setdefault((na_local, track_int), []).append(proc)

    def candidates_exact(self, nt):
        return self.title_groups.get(nt, [])

    def candidates_prefix(self, nt):
        return self.prefix_groups.get(_prefix(nt), [])

    def candidates_core(self, core_nt):
        return self.core_groups.get(core_nt, [])


def _dur_ok(want_s, have_s, tol):
    if not want_s or not have_s:
        return True  # missing duration is never a tiebreak veto
    return abs(want_s - have_s) <= tol


def _pick(cands, want_dur, pred, tol):
    """from cands keep those passing pred(); of those, prefer one with duration
    closest to want_dur and within tol. returns (proc, tier) or (None, None)."""
    kept = [c for c in cands if pred(c)]
    if not kept:
        return None, None
    if want_dur:
        within = [c for c in kept if have_ok(c, want_dur, tol)]
        if within:
            kept = within
        # else fall through to first-kept (we still accept, just note dur mismatch)
    chosen = min(kept, key=lambda c: (abs(c['length'] - want_dur) if want_dur else 0))
    return chosen, None


def have_ok(c, want_dur, tol):
    if not want_dur or not c['length']:
        return True
    return abs(c['length'] - want_dur) <= tol


def match_track(row, mindex):
    """row: playlist_tracks.csv dict. returns dict with tier, resolved path (or None),
    and the matched local title/artist/length for logging."""
    title = row.get('track_name') or ''
    artists = row.get('artist_names') or ''
    album = row.get('album_name') or ''
    try:
        want_dur = float(row.get('duration_ms') or 0) / 1000.0
    except (TypeError, ValueError):
        want_dur = 0.0

    if not title and not artists:
        return {'tier': 'local-no-meta', 'path': None, 'title': '', 'length': 0.0}

    nt = norm_key(title)
    raw = _raw_key(title)
    spot_artists = {norm_key(s) for s in _split_artists(artists)}
    spot_primary = norm_key(_primary_artist(artists))
    na = norm_key(album)
    track_num = _track_int(row.get('track_number'))

    if not nt:
        # all-symbol title (norm_key -> ""): tiers 1-5 are blind to it. resolve
        # by exact raw title first, then (album, track-number) position - both
        # guarded by artist/album/duration so a generic "$"/"!!" can't cross.
        return _match_symbol_only(mindex, raw, spot_artists, spot_primary,
                                 na, track_num, want_dur)

    # tier 1: exact title + primary-artist token match
    if spot_primary:
        proc, _ = _pick(
            mindex.candidates_exact(nt), want_dur,
            lambda c: spot_primary in c['artists'] or spot_primary == c['primary'] or c['primary'] in spot_artists,
            tol=5,
        )
        if proc:
            return _result(proc, 'title+primary')

    # tier 2: exact title + any artist overlap
    if spot_artists:
        proc, _ = _pick(
            mindex.candidates_exact(nt), want_dur,
            lambda c: spot_artists & c['artists'],
            tol=5,
        )
        if proc:
            return _result(proc, 'title+artist')

    # tier 3: exact title + exact album + duration (bootleg albums often differ,
    # so album is a guard here, not a requirement on its own)
    if na:
        proc, _ = _pick(
            mindex.candidates_exact(nt), want_dur,
            lambda c: c['album'] == na,
            tol=3,
        )
        if proc:
            return _result(proc, 'title+album')

    # tier 4: core title (feat. credit stripped off the local tag) + artist
    # overlap. rescues a local "U Know What's Up (feat. Lisa ...)" against a
    # spotify "U Know What's Up" when the exact-norm tiers miss on the suffix.
    # the spotify title is usually already clean, so core_q == nt; the lookup is
    # into core_groups, which only holds locals whose feat. parenthetical was
    # actually stripped (core_nt != nt) - no double-resolution of the exact case.
    core_q = norm_key(_core_title(title)) or nt
    if spot_artists:
        proc, _ = _pick(
            mindex.candidates_core(core_q), want_dur,
            lambda c: spot_artists & c['artists'] or spot_primary == c['primary'],
            tol=5,
        )
        if proc:
            return _result(proc, 'core-title')

    # tier 5: fuzzy title (same 4-char prefix) + duration; hesitant
    best = None
    best_ratio = 0.0
    for c in mindex.candidates_prefix(nt):
        if not _dur_ok(want_dur, c['length'], tol=3):
            continue
        r = difflib.SequenceMatcher(None, c['nt'], nt).ratio()
        if r > best_ratio:
            best_ratio = r
            best = c
    if best and best_ratio >= 0.92:
        return _result(best, 'fuzzy')

    return {'tier': 'unmatched', 'path': None, 'title': '', 'length': 0.0}


def _artist_or_album_ok(c, spot_artists, spot_primary, na):
    """guard for raw-title matches: accept if a credited artist overlaps or the
    artist-equivalent primary matches, else if the album matches. raw title
    alone is enough signal for the very rare symbol-only collision here, but a
    lone "$" must not bind to an unrelated track, so we require one anchor."""
    if spot_artists and (spot_artists & c['artists'] or spot_primary == c['primary']):
        return True
    if na and c['album'] == na:
        return True
    return False


def _match_symbol_only(mindex, raw, spot_artists, spot_primary, na, track_num, want_dur):
    """tier 5 fallback for all-symbol titles (norm_key == ""). two passes, each
    guarded:
      5a. exact raw-title (symbols preserved) + artist-or-album anchor, ±5s tiebreak.
      5b. (album, track-number) position + duration ±5s - rescues a raw mismatch
          (e.g. spotify "$$$" vs a tag written "$ $") when the album+position line up.
    """
    if raw:
        cands = mindex.raw_groups.get(raw, [])
        kept = [c for c in cands if _artist_or_album_ok(c, spot_artists, spot_primary, na)]
        if kept:
            chosen = min(kept, key=lambda c: (abs(c['length'] - want_dur) if want_dur else 0))
            if want_dur and not _dur_ok(want_dur, chosen['length'], tol=5):
                pass  # accept anyway - symbol titles rarely have a better fit
            return _result(chosen, 'raw-title')
    if na and track_num is not None:
        cands = mindex.albumtrack_groups.get((na, track_num), [])
        kept = [c for c in cands if _dur_ok(want_dur, c['length'], tol=5)]
        if kept:
            chosen = min(kept, key=lambda c: (abs(c['length'] - want_dur) if want_dur else 0))
            return _result(chosen, 'album+track')
    return {'tier': 'unmatched', 'path': None, 'title': '', 'length': 0.0}


def _result(proc, tier):
    e = proc['e']
    return {
        'tier': tier,
        'path': e.get('path'),
        'title': e.get('title') or '',
        'artist': e.get('artist') or '',
        'length': proc['length'],
    }


def match_rows(rows, mindex, verbose=False):
    """resolve a list of playlist_tracks rows, caching by track_id so a song in
    many playlists is matched once. returns list of {row, **result}."""
    cache = {}
    out = []
    for i, row in enumerate(rows, 1):
        tid = row.get('track_id')
        if tid and tid in cache:
            res = cache[tid]
        else:
            res = match_track(row, mindex)
            if tid:
                cache[tid] = res
        rec = {'row': row, **res}
        out.append(rec)
        if verbose:
            mark = '+' if res['path'] else '-'
            print(f"  [{mark}] {row.get('artist_names')} - {row.get('track_name')}  ({res['tier']})")
    return out
