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

  strip_edition_suffix(s) - same conservative shape as strip_feat_clause,
                           but for albums: removes only a trailing,
                           delimited edition/remaster/anniversary clause
                           ("(Deluxe)", "(Deluxe Edition)", "[Remastered]",
                           " - 2009 Remaster", "(25th Anniversary
                           Edition)"). A parenthetical that doesn't match
                           the edition-keyword pattern - "(Ohia)", "(Original
                           Soundtrack)" - is left untouched. normalize_album()
                           feeds this through normalize_key() for an actual
                           lookup/grouping key, same relationship
                           strip_feat_clause() has to normalize_key(). Used
                           by lib.catalog.matcher's album-keyed tiers (3,
                           6b) and by organize's grouping keys (both
                           organize.cleanup.grouping.group_files() and
                           organize.preimport.plan's merge-target index) so
                           an edition variant of an album merges/matches
                           against the plain release instead of forking
                           into a separate group.

split_artists() / primary_artist() are the shared artist-credit splitter
used by both the spotify dedup pass and the crate matcher.
"""

import re
import unicodedata

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

# conservative edition/remaster/anniversary suffix - only matched when
# delimited (parens/brackets, or a trailing dash/colon clause), never bare
# in the middle of a title, so a real album that happens to contain a
# parenthetical ("Songs (Ohia)", "The Wall (Original Soundtrack)") is never
# touched. See strip_edition_suffix()'s docstring for the intended cases.
_EDITION_INNER = (
    r"(?:\d{4}\s+)?"                                   # optional leading year, "2009 Remaster"
    r"(?:\d+(?:st|nd|rd|th)\s+)?"                       # optional ordinal, "25th Anniversary"
    r"(?:super\s+)?"
    r"(?:deluxe|remaster(?:ed)?|anniversary|expanded|"
    r"special|collector'?s?|platinum|extended|bonus\s+tracks?)"
    r"(?:\s+(?:edition|version|remaster(?:ed)?|anniversary))*"
    r"(?:\s+\d{4})?"                                    # optional trailing year, "Remastered 2009"
)

_EDITION_BRACKET_RE = re.compile(
    r'\s*[\(\[]\s*' + _EDITION_INNER + r'\s*[\)\]]\s*$', re.IGNORECASE
)
_EDITION_DASH_RE = re.compile(
    r'\s*[-\u2013\u2014:]\s*' + _EDITION_INNER + r'\s*$', re.IGNORECASE
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


def strip_edition_suffix(s):
    """remove only a trailing, delimited edition/remaster/anniversary
    clause - "(Deluxe)", "(Deluxe Edition)", "[Remastered]", " - 2009
    Remaster", "(25th Anniversary Edition)" - leaving everything else
    intact. Conservative like strip_feat_clause(): a parenthetical that
    doesn't match the edition-keyword pattern ("(Ohia)", "(Original
    Soundtrack)") is never touched. Stacked suffixes ("Title (Deluxe)
    (2011 Remaster)") are stripped iteratively."""
    if not s:
        return ''
    s = str(s)
    prev = None
    while prev != s:
        prev = s
        s = _EDITION_BRACKET_RE.sub('', s)
        s = _EDITION_DASH_RE.sub('', s)
        s = s.rstrip()
    return s


def normalize_album(s):
    """canonical album identity for matching/grouping: strip a trailing
    edition/remaster/anniversary clause, then normalize_key(). Feeds
    lib.catalog.matcher's album-keyed tiers and organize's grouping keys
    so "Title" and "Title (Deluxe)"/"Title (2009 Remaster)" resolve to
    the same identity without requiring the literal strings to match."""
    return normalize_key(strip_edition_suffix(s))


def group_key(s):
    """Unicode-aware grouping key: NFKC → casefold → keep \\w (letters/digits in any script).
    Never returns '' for non-blank input; if everything strips, fall back to casefold(strip(s)).
    Used for organize grouping (Bug 4)."""
    if not s:
        return ''
    # NFKC normalization
    normalized = unicodedata.normalize('NFKC', s)
    # casefold
    folded = normalized.casefold()
    # keep only word characters (letters/digits in any script)
    kept = ''.join(c for c in folded if unicodedata.category(c)[0] in 'LN')
    # if we kept something, return it; otherwise fall back to casefold(strip(s))
    if kept:
        return kept
    return folded.strip()


def group_album_key(s):
    """Group key for albums: apply group_key to the string with edition suffix stripped.
    Used for organize grouping (Bug 4)."""
    return group_key(strip_edition_suffix(s))


def fold_key(s):
    """NFKD, drop combining marks, lowercase, keep [a-z0-9]. Used only by matcher veto.
    '' means "no evidence" (non-Latin), never a contradiction (Bug 11)."""
    if not s:
        return ''
    # NFKD normalization
    normalized = unicodedata.normalize('NFKD', s)
    # drop combining marks (category starts with 'M')
    no_combining = ''.join(c for c in normalized if unicodedata.category(c)[0] != 'M')
    # lowercase
    lowered = no_combining.lower()
    # keep only ASCII alphanumerics
    kept = ''.join(c for c in lowered if c.isascii() and c.isalnum())
    return kept


# Allowlist for artist credits that contain '/' but should be rendered with '_' instead of being split
# Built from Phase 3 dry run output - review distinct '/'-containing credits with counts
# TODO: Move this allowlist to lib.tags to avoid circular dependency, or provide a getter function
_LEGITIMATE_SLASH_CREDITS = {
    'AC/DC',  # Placeholder - should be reviewed and updated based on actual dry run
}


def render_credit(raw):
    """render artist credit for path construction: split on '/' only, join with ', ';
    '&' and ',' inside credits left untouched (D1).
    Legitimate slash-containing credits (from allowlist) are rendered with '_' (beets-style)."""
    if not raw:
        return ''
    raw_str = str(raw)
    # Check if this is a known legitimate slash credit that should not be split
    if raw_str in _LEGITIMATE_SLASH_CREDITS:
        # Render with '_' replacing '/' (beets-style)
        return raw_str.replace('/', '_')
    # Split on '/' only (the tag-level multi-value delimiter)
    parts = [p.strip() for p in raw_str.split('/') if p and p.strip()]
    # Join with ', ' (D1 decision)
    return ', '.join(parts)


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

    # strip_edition_suffix / normalize_album: conservative edition stripping,
    # delimiter-anchored (parens/brackets/dash) so it never fires bare
    # mid-title
    assert strip_edition_suffix('Title (Deluxe)') == 'Title'
    assert strip_edition_suffix('Title (Deluxe Edition)') == 'Title'
    assert strip_edition_suffix('Title (25th Anniversary Edition)') == 'Title'
    assert strip_edition_suffix('Title (Remastered)') == 'Title'
    assert strip_edition_suffix('Title (Remaster)') == 'Title'
    assert strip_edition_suffix('Title (2009 Remaster)') == 'Title'
    assert strip_edition_suffix('Title (Remastered 2009)') == 'Title'
    assert strip_edition_suffix('Title - Remastered') == 'Title'
    assert strip_edition_suffix('Title [Deluxe]') == 'Title'
    assert strip_edition_suffix('Title (Deluxe) (2011 Remaster)') == 'Title'
    # doesn't touch parens that aren't an edition clause
    assert strip_edition_suffix('Songs (Ohia)') == 'Songs (Ohia)'
    assert strip_edition_suffix('The Wall (Original Soundtrack)') == 'The Wall (Original Soundtrack)'
    assert strip_edition_suffix('Title') == 'Title'
    assert strip_edition_suffix('') == ''
    # feeding it through normalize_key() is the actual intended use
    assert normalize_album('Title (Deluxe Edition)') == normalize_album('Title')
    assert normalize_album('Title (Ohia)') != normalize_album('Title')

    # symbol-only titles: normalize_key/normalize_title reduce to '', not an
    # error - callers (see lib.catalog.matcher tier 6) rely on this to
    # detect the "nothing left after stripping" case.
    assert normalize_key('$$$') == ''
    assert normalize_title('$$$') == ''
    assert normalize_key('!!!') == ''

    # group_key: Unicode-aware, never '' for non-blank input
    assert group_key('Hello, World!') == 'helloworld'
    assert group_key('') == ''
    assert group_key('Hello') == 'hello'
    assert group_key('Café') == 'café'  # accent preserved
    assert group_key('🚀') == '🚀'  # emoji preserved (it's a letter in Unicode)
    # group_key: Unicode-aware, never '' for non-blank input
    # Never returns '' for a non-blank input; if everything strips, fall back to casefold(strip(s))
    # So for '!!!', after NFKC and casefold, we still have '!!!', then we try to keep \w characters, but there are none,
    # so we fall back to casefold(strip(s)) = '!!!'. But strip(s) of '!!!' is '!!!', so casefold is '!!!'.
    # So group_key('!!!') should be '!!!', not ''.
    assert group_key('!!!') == '!!!'  # symbols only -> fall back to casefold(strip(s))

    # group_album_key: just group_key after stripping edition suffix
    assert group_album_key('Title (Deluxe)') == group_key('Title')
    assert group_album_key('Title') == group_key('Title')

    # fold_key: NFKD, drop combining marks, lowercase, keep [a-z0-9]
    assert fold_key('Jhené') == fold_key('Jhene')  # accent folded
    assert fold_key('ぬいぐるみ') == ''  # non-Latin -> no evidence
    assert fold_key('Hello123') == 'hello123'
    assert fold_key('Hello_World!') == 'helloworld'  # underscore kept? Wait, [a-z0-9] only, so underscore removed
    # Actually, [a-z0-9] means only lowercase letters and digits, so underscore should be removed
    assert fold_key('Hello_World!') == 'helloworld'

    # render_credit: split on '/' only, join with ', '; '&' and ',' inside credits untouched
    assert render_credit('Run The Jewels/El-P/Killer Mike') == 'Run The Jewels, El-P, Killer Mike'
    assert render_credit('King Gizzard & The Lizard Wizard') == 'King Gizzard & The Lizard Wizard'
    assert render_credit('Simon & Garfunkel') == 'Simon & Garfunkel'
    assert render_credit('Tyler, The Creator') == 'Tyler, The Creator'
    assert render_credit('AC/DC') == 'AC_DC'  # Legitimate slash credit -> rendered with '_'
    assert render_credit('') == ''
    assert render_credit(None) == ''

    print('lib.text sanity checks: ok')


if __name__ == '__main__':
    _run_sanity_checks()
