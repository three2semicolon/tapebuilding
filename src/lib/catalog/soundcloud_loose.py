"""lib.catalog.soundcloud_loose - last-resort, SoundCloud-only matching tiers.

Why this exists
---------------
SoundCloud rows are a different shape from spotify rows:

  * ~90% of them carry a title rebuilt from the URL *slug*
    ("captain-murphy-immaculation-ft" -> "captain murphy immaculation ft"):
    punctuation/apostrophes gone ("doesnt", "its"), the real artist often
    glued onto the front of the title, and trailing junk ("ft", "prod by x",
    "premiere", "free download").
  * `artist_names` is the *uploader*, which is frequently a label or a
    re-uploader (Monstercat, BRAINFEEDER, SOULECTION, selftitledmag...), not
    the artist who is in the local file's tags.

The spotify-shaped tiers 1-6 need an exact/core title key plus artist
overlap, so they can't see any of that. These tiers run AFTER tier 6, only
for SoundCloud rows, so they can never change an existing match.

  tier 7  soundcloud_artist_title   local title found inside the row text AND
                                    a local artist found in the row text/uploader
  tier 8  soundcloud_fuzzy_title    same artist evidence, title only *close*
                                    (difflib ratio), after artist is removed
  tier 9  soundcloud_title_only     no artist evidence at all, but the local
                                    title is long/distinctive and UNIQUE in the
                                    library (lowest confidence - audit these)

Self-contained on purpose: only depends on .row_access.
"""

import collections
import difflib
import os
import re
import unicodedata

from .row_access import _row_get, _row_duration_seconds

# ---- tunables ---------------------------------------------------------
FUZZY_TITLE_RATIO = 0.86          # tier 8 title similarity (after artist removed)
FUZZY_ARTIST_RATIO = 0.88         # uploader ~ local artist
MAX_DURATION_DIFF = 15.0          # seconds; only vetoes when BOTH durations known
TITLE_ONLY_MIN_CHARS = 12         # tier 9: joined title must be at least this long...
TITLE_ONLY_MIN_TOKENS = 2         # ...AND at least this many words
PREFIX_MIN_CHARS = 5              # truncated-slug rule: row text (artist removed) at least this long
PREFIX_MAX_MISSING_WORDS = 2      # ...and at most this many words of the local title missing
ALLOW_TITLE_ONLY = True           # set False to drop tier 9 entirely

# ---- vocab ------------------------------------------------------------
_REMIX_MARKERS = {'remix', 'flip', 'bootleg', 'rework', 'vip', 'refix', 'edit', 'dub', 'mashup'}
_NOT_A_REMIX_EDIT_PREFIX = {'radio', 'extended', 'album', 'clean', 'explicit', 'single', 'original', 'club'}
_VERSION_WORDS = {'original', 'mix', 'extended', 'radio', 'version', 'official', 'audio', 'video',
                  'lyric', 'lyrics', 'hq', 'hd', 'remastered', 'remaster'}
_NOISE_PHRASES = [
    ('free', 'download'), ('free', 'dl'), ('download', 'in', 'description'),
    ('all', 'platforms'), ('out', 'now'), ('buy', 'free'), ('premiere',), ('snippet',),
    ('preview',), ('clip',),
]
_GENERIC_ARTIST_TOKENS = {'dj', 'the', 'mc', 'a', 'and', 'x', 'of', 'official', 'music',
                          'records', 'recordings', 'prod', 'productions', 'vs', 'artist',
                          'beats', 'audio', 'band', 'label'}
# glue words / slug leftovers that carry no identity once the artist is removed.
# '1' is here because SoundCloud slugs append it to de-duplicate ("hz-1").
_FREE_LEFTOVER = {'ft', 'feat', 'featuring', 'prod', 'by', 'w', 'x', 'vs', 'with', 'and', '1'}
_PROD_MARKERS = [('prod', 'by'), ('prod',), ('produced', 'by'), ('beat', 'by'), ('beats', 'by')]
_FEAT_MARKERS = [('feat',), ('ft',), ('featuring',), ('w',), ('with',)]

_BRACKET_NOISE_RE = re.compile(
    r'[\[\(][^\]\)]*\b(premiere|free\s*(dl|download)|download|snippet|platforms?|out\s*now|'
    r'buy|preview)\b[^\]\)]*[\]\)]', re.I)
_BRACKET_RE = re.compile(r'[\[\(][^\]\)]*[\]\)]')
_FEAT_CLAUSE_RE = re.compile(r'[\[\(]\s*(feat|ft|featuring|with|w)\b[^\]\)]*[\]\)]|\s(feat|ft|featuring)\.?\s.*$', re.I)
_ARTIST_SPLIT_RE = re.compile(r'\s*(?:_|,|;|&|/|\+|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b|\bx\b|\band\b|\bvs\.?)\s*', re.I)


# ---- tokenizing -------------------------------------------------------
def tokens(s):
    """NFKD fold (strips accents, folds fullwidth), casefold, drop apostrophes,
    everything else non-alphanumeric becomes a separator."""
    if not s:
        return ()
    s = unicodedata.normalize('NFKD', str(s))
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold().replace("'", '').replace('\u2019', '').replace('`', '')
    s = ''.join(ch if ch.isalnum() else ' ' for ch in s)
    return tuple(s.split())


def _find(seq, sub):
    """index of contiguous subsequence `sub` in `seq`, or -1."""
    n, m = len(seq), len(sub)
    if m == 0 or m > n:
        return -1
    for i in range(n - m + 1):
        if seq[i:i + m] == sub:
            return i
    return -1


def _strip_phrases(toks, phrases):
    out, i = [], 0
    while i < len(toks):
        for ph in phrases:
            if toks[i:i + len(ph)] == ph:
                i += len(ph)
                break
        else:
            out.append(toks[i])
            i += 1
    return tuple(out)


def _cut_at(toks, markers):
    """truncate at the first occurrence of any marker phrase (not at index 0)."""
    best = None
    for m in markers:
        idx = _find(toks, m)
        if idx > 0 and (best is None or idx < best):
            best = idx
    return toks if best is None else toks[:best]


def _has_marker(toks):
    return any(t in _REMIX_MARKERS for t in toks)


def _entry_has_remix(title):
    """remix marker present in the local title's bracketed part (so
    "Song (Radio Edit)" doesn't count as a remix)."""
    for grp in _BRACKET_RE.findall(title or ''):
        t = tokens(grp)
        for i, w in enumerate(t):
            if w in _REMIX_MARKERS and not (w == 'edit' and i > 0 and t[i - 1] in _NOT_A_REMIX_EDIT_PREFIX):
                return True
    return False


def _find_seg(left, seg):
    """locate artist segment `seg` in token tuple `left` -> (index, n_tokens) or (-1, 0).
    tries a contiguous match, then a *collapsed* one so "c y g n" == "cygn"."""
    i = _find(left, seg)
    if i >= 0:
        return i, len(seg)
    joined = ''.join(seg)
    if len(joined) >= 3:
        for size in (1, 2, 3, 4):
            for j in range(len(left) - size + 1):
                if ''.join(left[j:j + size]) == joined:
                    return j, size
    return -1, 0


def _sig_collapsed(toks):
    return ''.join(t for t in toks if t not in _GENERIC_ARTIST_TOKENS)


_FILE_ARTIST_SPLIT_RE = re.compile(r'\s*(?:_|,|;|&|/|\+|\bfeat\.?|\bft\.?|\bx\b|\band\b)\s*', re.I)


def _filename_parts(path):
    """("Artist_A_Artist B", "Title") from '09 - Artist - Title.ext' /
    'Artist_B - Title.ext' style names. either part may be ''."""
    stem = os.path.splitext(os.path.basename(path or ''))[0]
    stem = re.sub(r'^\s*(?:\d{1,3}\s*[-._)]\s*)+', '', stem)     # leading track number
    parts = [p.strip() for p in re.split(r'\s+-\s+', stem) if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return '', (parts[0] if parts else '')


# ---- per-entry precompute ---------------------------------------------
class _Entry:
    __slots__ = ('entry', 'bases', 'base', 'base_str', 'paren_toks', 'remix', 'segs', 'seg_strs', 'length')

    def __init__(self, entry):
        self.entry = entry
        title = entry.get('title') or ''
        no_feat = _FEAT_CLAUSE_RE.sub(' ', title)
        self.remix = _entry_has_remix(no_feat)
        self.paren_toks = set(t for grp in _BRACKET_RE.findall(no_feat) for t in tokens(grp))
        self.base = tokens(_BRACKET_RE.sub(' ', no_feat)) or tokens(no_feat)
        self.base_str = ' '.join(self.base)
        # title candidates: the tag, plus the filename's title if it differs
        # (covers empty/garbled title tags)
        f_artist, f_title = _filename_parts(entry.get('path'))
        bases = [self.base] if self.base else []
        # ...and the title WITH its bracketed part, since SoundCloud titles carry it as
        # plain words: "Girls_Tequila (Kiss In The Club)" -> girls tequila kiss in the club
        full = tokens(no_feat)
        if full and full not in bases:
            bases.append(full)
        f_base = tokens(_BRACKET_RE.sub(' ', _FEAT_CLAUSE_RE.sub(' ', f_title)))
        if f_base and f_base not in bases:
            bases.append(f_base)
        self.bases = bases
        if not self.base and f_base:
            self.base, self.base_str = f_base, ' '.join(f_base)
        segs = set()
        raws = [(entry.get('artist'), _ARTIST_SPLIT_RE), (entry.get('albumartist'), _ARTIST_SPLIT_RE),
                (f_artist, _FILE_ARTIST_SPLIT_RE)]
        for raw, splitter in raws:
            raw = raw or ''
            full = tokens(raw)
            if full:
                segs.add(full)
            for part in splitter.split(raw):
                t = tokens(part)
                if t:
                    segs.add(t)
        # drop segments that are nothing but generic filler ("va", "the")
        self.segs = [s for s in segs if any(t not in _GENERIC_ARTIST_TOKENS for t in s)
                     and s not in {('various', 'artists'), ('va',)}]
        self.seg_strs = [' '.join(s) for s in self.segs]
        try:
            self.length = float(entry.get('length') or 0) or None
        except (TypeError, ValueError):
            self.length = None


# ---- row variants -----------------------------------------------------
def _row_variants(raw_title):
    """candidate token-tuples for the row title, most-literal first.
    each variant has junk progressively removed."""
    s = _BRACKET_NOISE_RE.sub(' ', raw_title or '')
    base = _strip_phrases(tokens(s), _NOISE_PHRASES)
    base = tuple(t for t in base if t not in _VERSION_WORDS) or base
    variants = []

    def add(v):
        v = tuple(v)
        if v and v not in variants:
            variants.append(v)

    add(base)
    no_prod = _cut_at(base, _PROD_MARKERS)
    add(no_prod)
    no_feat = _cut_at(base, _FEAT_MARKERS)
    add(no_feat)
    add(_cut_at(no_prod, _FEAT_MARKERS))
    # leading track number from a slug/filename ("03 glow")
    for v in list(variants):
        if len(v) > 1 and v[0].isdigit() and len(v[0]) <= 3:
            add(v[1:])
    # trailing dangling connector from a slug that lost its guest name ("... ft")
    for v in list(variants):
        while v and v[-1] in {'ft', 'feat', 'w', 'x', 'prod', 'by', 'and', 'vs'}:
            v = v[:-1]
            add(v)
    return variants


# ---- the index --------------------------------------------------------
class SoundcloudLooseIndex:
    def __init__(self, catalog):
        self.entries = [_Entry(e) for e in catalog
                        if ((e.get('title') or '').strip() or _filename_parts(e.get('path'))[1])]
        self.by_first = collections.defaultdict(list)     # first title token -> [_Entry]
        self.by_artist = collections.defaultdict(list)    # joined artist seg -> [_Entry]
        self.by_artist_c = collections.defaultdict(list)  # collapsed artist seg ("cygn") -> [_Entry]
        self.by_title = collections.defaultdict(list)     # joined base title -> [_Entry]
        for e in self.entries:
            for b in e.bases:
                self.by_first[b[0]].append(e)
                self.by_title[' '.join(b)].append(e)
            for seg, sstr in zip(e.segs, e.seg_strs):
                self.by_artist[sstr].append(e)
                c = _sig_collapsed(seg)
                if len(c) >= 3:
                    self.by_artist_c[c].append(e)
        self._artist_keys = list(self.by_artist_c)

    # -- artist evidence ---------------------------------------------------
    @staticmethod
    def _uploader_matches(seg, seg_str, up_toks, up_str):
        """is the local artist segment plausibly the SoundCloud uploader?"""
        if not up_toks:
            return False
        if seg_str == up_str:
            return True
        seg_c, up_c = _sig_collapsed(seg), _sig_collapsed(up_toks)
        if len(seg_c) >= 3 and seg_c == up_c:          # "c y g n" == "cygn artist"
            return True
        sig_seg = {t for t in seg if t not in _GENERIC_ARTIST_TOKENS}
        sig_up = {t for t in up_toks if t not in _GENERIC_ARTIST_TOKENS}
        if sig_seg and sig_up and (sig_seg <= sig_up or sig_up <= sig_seg):
            if min(len(seg_c), len(up_c)) >= 4:
                return True
        if len(seg_c) >= 4 and len(up_c) >= 4:
            return difflib.SequenceMatcher(None, seg_c, up_c).ratio() >= FUZZY_ARTIST_RATIO
        return False

    def _candidates(self, variants, up_toks, up_str):
        seen, out = set(), []

        def add(lst):
            for e in lst:
                if id(e) not in seen:
                    seen.add(id(e))
                    out.append(e)

        for v in variants:
            for t in set(v):
                add(self.by_first.get(t, ()))
            n = len(v)
            for size in (1, 2, 3, 4):
                for i in range(n - size + 1):
                    span = v[i:i + size]
                    add(self.by_artist.get(' '.join(span), ()))
                    add(self.by_artist_c.get(_sig_collapsed(span), ()))
        up_c = _sig_collapsed(up_toks)
        if len(up_c) >= 3:
            exact = self.by_artist_c.get(up_c)
            if exact:
                add(exact)
            else:
                for k in difflib.get_close_matches(up_c, self._artist_keys, n=3, cutoff=FUZZY_ARTIST_RATIO):
                    add(self.by_artist_c[k])
        return out

    def _artist_evidence(self, left, ent, up_toks, up_str):
        """-> (left_after_artist, how) or None. removes EVERY local artist segment
        found in the row text (multi-artist "A_B"/"A/B" files), not just the first."""
        removed = False
        for seg in sorted(ent.segs, key=len, reverse=True):
            if len(''.join(seg)) < 3:
                continue
            i, n = _find_seg(left, seg)
            if i >= 0:
                left = left[:i] + left[i + n:]
                removed = True
        if removed:
            return left, 'title'
        for seg, sstr in zip(ent.segs, ent.seg_strs):
            if self._uploader_matches(seg, sstr, up_toks, up_str):
                return left, 'uploader'
        # remixer uploading their own remix: uploader == the name in "(X Remix)"
        if ent.remix:
            sig_up = {t for t in up_toks if t not in _GENERIC_ARTIST_TOKENS}
            if sig_up and sig_up <= ent.paren_toks and len(' '.join(sorted(sig_up))) >= 4:
                return left, 'uploader'
        return None

    # -- scoring one (variant, entry) pair -----------------------------------
    def _score(self, variant, ent, up_toks, up_str, row_remix, want_dur):
        """returns (score, tier, kind) or None; kind in {'', 'prefix'}; best over the entry's title candidates."""
        if not ent.bases or (ent.remix != row_remix):
            return None
        if want_dur and ent.length and abs(want_dur - ent.length) > MAX_DURATION_DIFF:
            return None

        def clean_left(left):
            if ent.remix:   # tolerate remix markers carried in the local brackets
                left = tuple(t for t in left if t not in _REMIX_MARKERS)
            # words that live in the local title's own brackets are explained, not leftover
            left = tuple(t for t in left if t not in ent.paren_toks)
            return tuple(t for t in left if t not in _FREE_LEFTOVER)

        best = None
        for base in ent.bases:
            base_str = ' '.join(base)
            # --- tier 7: local title contiguous inside the row text -----------------
            i = _find(variant, base)
            if i >= 0:
                left = variant[:i] + variant[i + len(base):]
                ev = self._artist_evidence(left, ent, up_toks, up_str)
                if ev is not None:
                    left, how = ev
                    left = clean_left(left)
                    allowed = 1 if len(base) == 1 else 2
                    short = len(base) == 1 and len(base[0]) <= 3
                    if len(left) <= allowed and not (short and left):
                        res = (1.0 - 0.08 * len(left) + (0.03 if how == 'title' else 0.0), 7, '')
                        best = res if best is None or res[0] > best[0] else best
                        continue
            # --- tier 8: fuzzy title after the artist is taken out ---------------------
            ev = self._artist_evidence(variant, ent, up_toks, up_str)
            if ev is not None:
                rest = clean_left(ev[0])
                rest_str = ' '.join(rest)
                if len(rest_str) >= 5 and len(base_str) >= 5:
                    if rest_str.replace(' ', '') == base_str.replace(' ', ''):
                        res = (0.95, 7, '')           # "on my mind" == "OnMyMind"
                    else:
                        ratio = difflib.SequenceMatcher(None, rest_str, base_str).ratio()
                        res = (ratio - 0.1, 8, '') if ratio >= FUZZY_TITLE_RATIO else None
                    if res and (best is None or (res[1], -res[0]) < (best[1], -best[0])):
                        best = res
                # truncated slug: the row text is a PREFIX of the local title
                # ("living off the" -> "Living Off the High"), 1-2 words missing.
                if rest and len(rest_str) >= PREFIX_MIN_CHARS and len(rest) < len(base):
                    missing = len(base) - len(rest)
                    head, last = base[:len(rest) - 1], base[len(rest) - 1]
                    if (missing <= PREFIX_MAX_MISSING_WORDS and rest[:-1] == head
                            and (rest[-1] == last)):
                        res = (0.80 - 0.05 * missing, 8, 'prefix')
                        if best is None or (res[1], -res[0]) < (best[1], -best[0]):
                            best = res
                    elif (len(rest[-1]) >= 4 and rest[:-1] == head and last.startswith(rest[-1])
                          and missing <= PREFIX_MAX_MISSING_WORDS - 1):
                        # last word itself cut mid-way ("thoug" -> "thoughts")
                        res = (0.70 - 0.05 * missing, 8, 'prefix')
                        if best is None or (res[1], -res[0]) < (best[1], -best[0]):
                            best = res
        return best

    # -- public --------------------------------------------------------------
    def match(self, row):
        raw_title = _row_get(row, 'track_name', 'title', 'name', default='') or ''
        raw_artist = _row_get(row, 'artist_names', 'artist', 'artists', default='') or ''
        variants = _row_variants(raw_title)
        if not variants:
            return None, None
        up_toks = tokens(raw_artist)
        up_str = ' '.join(up_toks)
        row_remix = _has_marker(variants[0])
        want_dur = _row_duration_seconds(row)

        best = None            # (tier, -score, entry, kind)
        prefix_hits = set()    # distinct entries that matched only as a truncated prefix
        for ent in self._candidates(variants, up_toks, up_str):
            for v in variants:
                res = self._score(v, ent, up_toks, up_str, row_remix, want_dur)
                if res is None:
                    continue
                score, tier, kind = res
                if kind == 'prefix':
                    prefix_hits.add(id(ent))
                if want_dur and ent.length and abs(want_dur - ent.length) <= 3:
                    score += 0.1
                cand = (tier, -score, ent.entry, kind)
                if best is None or cand[:2] < best[:2]:
                    best = cand
        if best is not None:
            # a prefix is only trustworthy when it's unambiguous: "pretty" must not
            # pick between "Pretty Thoughts" and "Pretty Girl" by luck
            if best[3] == 'prefix' and len(prefix_hits) > 1:
                best = None
            else:
                return best[2], best[0]
        if ALLOW_TITLE_ONLY:
            return self._title_only(variants, row_remix, want_dur)
        return None, None

    def _title_only(self, variants, row_remix, want_dur):
        """tier 9: the row text IS a distinctive local title that occurs exactly once."""
        for v in variants:
            key = ' '.join(v)
            ents = [e for e in self.by_title.get(key, ()) if e.remix == row_remix]
            if len(ents) != 1:
                continue
            e = ents[0]
            if len(key) < TITLE_ONLY_MIN_CHARS or len(v) < TITLE_ONLY_MIN_TOKENS:
                continue   # must be BOTH long and multi-word, or it's not distinctive
            if want_dur and e.length and abs(want_dur - e.length) > MAX_DURATION_DIFF:
                continue
            return e.entry, 9
        return None, None
