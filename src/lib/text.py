"""lib.text - shared string normalization for grouping, matching, and dedup.

three distinct transforms live here on purpose - they solve different
problems, and collapsing them into one "normalize" would change behavior:

  normalize_key(s)      - bare grouping key: lowercase, alphanumeric only,
                           no whitespace. used wherever two strings just need
                           to compare equal after case/punctuation noise is
                           removed (album/artist grouping, filename stems,
                           library indexing).

  normalize_title(s)    - aggressive dedup key for spotify track titles:
                           drops a featuring credit *and everything after
                           it*, drops all parenthetical content, then
                           normalizes. used for collapsing remasters/
                           regional versions during spotify export dedup -
                           deliberately lossy, not for exact-match lookups.

  strip_feat_clause(s)  - conservative: removes only an explicit bracketed
                           featuring/ft./with/vs credit, leaves everything
                           else intact (including "(Remix)"/"(Radio Edit)").
                           used before normalize_key() when matching a local
                           file tag that kept a "(feat. X)" suffix against a
                           clean spotify title - two different real songs
                           that happen to share a feat-stripped name still
                           won't collide on this alone, since it isn't a
                           lookup key by itself.

split_artists() / primary_artist() are the shared artist-credit splitter
used by both the spotify dedup pass and the crate matcher.
"""

import re

_FEAT_TO_END_RE = re.compile(r'\s*(feat\.?|ft\.?|featuring)\s+.*', re.IGNORECASE)
_ANY_PAREN_RE = re.compile(r'\s*\(.*?\)')
_NON_WORD_RE = re.compile(r'[^\w\s]')
_WS_RE = re.compile(r'\s+')
_NON_ALNUM_RE = re.compile(r'[^a-z0-9]')

_FEAT_PAREN_RE = re.compile(
    r'\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring|with|vs\.?)\b[^)\]]*[\)\]]\s*',
    re.IGNORECASE,
)

_ARTIST_SPLIT_RE = re.compile(
    r'\s*(?:,|&|/| x | vs | feat\.?|ft\.?|featuring)\s*', re.IGNORECASE
)


def normalize_key(s):
    """lowercase, alphanumeric-only, no whitespace - the bare grouping key."""
    return _NON_ALNUM_RE.sub('', (s or '').lower())


def normalize_title(s):
    """aggressive dedup key: drop a feat. credit and everything after it,
    drop parenthetical content, strip symbols, collapse whitespace."""
    if not s:
        return ''
    s = s.lower()
    s = _FEAT_TO_END_RE.sub('', s)
    s = _ANY_PAREN_RE.sub('', s)
    s = _NON_WORD_RE.sub('', s)
    s = _WS_RE.sub(' ', s).strip()
    return s


def strip_feat_clause(s):
    """remove only an explicit bracketed feat./ft./featuring/with/vs credit;
    leave everything else intact. pass the result through normalize_key()
    for an actual lookup key."""
    if not s:
        return ''
    return ' '.join(_FEAT_PAREN_RE.sub(' ', str(s)).split())


def split_artists(s):
    """split an artist credit string on comma/&//  x / vs / feat separators
    into a list of stripped names."""
    if not s:
        return []
    parts = [p.strip() for p in _ARTIST_SPLIT_RE.split(s) if p and p.strip()]
    return [p for p in parts if p]


def primary_artist(s):
    """first credited artist from a split_artists() result."""
    parts = split_artists(s)
    return parts[0] if parts else ''


def _run_sanity_checks():
    """inline regression checks - `python -m lib.text` to run.

    this module is used everywhere downstream (matching, dedup, indexing),
    so a silent regression here has a wide blast radius. not a full test
    suite - just the cases the docstring above calls out explicitly.
    """
    # normalize_key: bare grouping key
    assert normalize_key(' Hello, World! ') == 'helloworld'
    assert normalize_key('') == ''
    assert normalize_key(None) == ''

    # normalize_title: feat. stripping (and everything after it)
    assert normalize_title('Song feat. Other Artist') == 'song'
    assert normalize_title('Song Ft. Other') == 'song'
    assert normalize_title('Song featuring Other') == 'song'
    # ... plus parenthetical content, independent of feat. stripping
    assert normalize_title('Song (Radio Edit)') == 'song'
    assert normalize_title('Song (feat. Other) (Remix)') == 'song'
    # collapsing to the same dedup key is the actual point of this function
    assert normalize_title('Song (feat. Other)') == normalize_title('Song')

    # strip_feat_clause: conservative - only the bracketed feat/ft/with/vs
    # clause, everything else (including other parens) survives
    assert strip_feat_clause('Title (feat. X)') == 'Title'
    assert strip_feat_clause('Title (Remix)') == 'Title (Remix)'
    assert strip_feat_clause('Title [ft. X]') == 'Title'
    assert strip_feat_clause('Title (with X)') == 'Title'
    assert strip_feat_clause('Title (vs X)') == 'Title'
    assert strip_feat_clause('Title') == 'Title'
    # feeding it through normalize_key() is the actual intended use
    assert normalize_key(strip_feat_clause('Title (feat. X)')) == normalize_key('Title')

    # split_artists / primary_artist: comma, &, /, ' x ', ' vs ', feat family
    assert split_artists('A, B & C') == ['A', 'B', 'C']
    assert split_artists('A / B') == ['A', 'B']
    assert split_artists('A x B') == ['A', 'B']
    assert split_artists('A vs B') == ['A', 'B']
    assert split_artists('A feat. B') == ['A', 'B']
    assert split_artists('A ft. B') == ['A', 'B']
    assert split_artists('A featuring B') == ['A', 'B']
    assert split_artists('Solo Artist') == ['Solo Artist']
    assert split_artists('') == []
    assert primary_artist('A, B & C') == 'A'
    assert primary_artist('') == ''
    # NOTE: unlike organize/normalize_artists.py's beets plugin (a separate,
    # deliberately untouched subsystem - see PACKAGE_OVERVIEW.md), plain
    # " and " is NOT a split point here. "A and B" is one credited name as
    # far as lib.text is concerned - matches playlists/matcher.py's original
    # _split_artists, ported as-is. flagging this explicitly since it's an
    # easy assumption to get backwards.
    assert split_artists('A and B') == ['A and B']

    # symbol-only titles: normalize_key/normalize_title reduce to '', not an
    # error - callers (see lib.catalog.matcher tier 6) rely on this to
    # detect the "nothing left after stripping" case.
    assert normalize_key('$$$') == ''
    assert normalize_title('$$$') == ''
    assert normalize_key('!!!') == ''

    print('lib.text sanity checks: ok')


if __name__ == '__main__':
    _run_sanity_checks()
