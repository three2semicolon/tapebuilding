"""Tests for lib.catalog.matcher - TEST_PLANS.md 'lib/catalog/matcher.py'
section.

Written against the actual current source. No skeleton existed for this
module yet, so this is built fresh from TEST_PLANS.md's spec plus the
module's own docstring - which is worth reading before touching this file,
since it documents six specific ways an earlier rebuild of this exact
module drifted from the real behavior. Several tests below (the
per-tier-isolation tests, the symbol-title index-exclusion test) exist
specifically to pin down those six points so a future edit can't
reintroduce the same drift silently.

Each tier test is deliberately constructed so ONLY that tier's predicate
can succeed - see each test's inline comment for why the earlier tiers
miss. This matters because match()/tier order means a test that's "loose"
about earlier tiers can pass for the wrong reason (e.g. actually matching
via tier 1 while claiming to test tier 4) and wouldn't catch a real
tier-ordering regression.

Catalog entries use lib.tags.read_tags()'s shape: {path, artist,
albumartist, album, title, track, length}. Rows mimic the real
spotify_manifest.csv / playlists_manifest.csv columns (track_name,
artist_names, album_name, duration_ms, track_number, track_id) - see
_row_get() / _row_title() etc. in the source for the accepted fallback
column names.
"""
import pytest

from lib.catalog.matcher import (
    MatchIndex,
    match_rows,
    tier_name,
    _row_duration_seconds,
    _row_track_number,
)


def _entry(**kw):
    base = {
        "path": "/crate/track.mp3",
        "artist": "",
        "albumartist": "",
        "album": "",
        "title": "",
        "track": 0,
        "length": 0.0,
    }
    base.update(kw)
    return base


def _row(**kw):
    base = {"track_name": "", "artist_names": ""}
    base.update(kw)
    return base


class TestTiersInIsolation:
    def test_tier1_exact_title_and_primary_artist(self):
        catalog = [_entry(title="Midnight Drive", artist="Nova", path="/crate/nova.mp3")]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(_row(track_name="Midnight Drive", artist_names="Nova"))
        assert tier == 1
        assert entry["path"] == "/crate/nova.mp3"

    def test_tier2_exact_title_artist_overlap_without_primary_match(self):
        # entry primary is "Nova", row primary is "Zephyr" - tier 1's three
        # OR-conditions all fail. But both credits include "Kade", so
        # tier 2's plain-overlap predicate succeeds.
        catalog = [_entry(title="Neon Skyline", artist="Nova, Kade", path="/crate/collab.mp3")]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(_row(track_name="Neon Skyline", artist_names="Zephyr, Kade"))
        assert tier == 2
        assert entry["path"] == "/crate/collab.mp3"

    def test_tier3_exact_title_and_album_with_zero_artist_overlap(self):
        # no shared artist token at all - tiers 1 and 2 both miss - but the
        # album matches exactly.
        catalog = [
            _entry(title="Static", artist="Nova", album="Waveforms", path="/crate/static.mp3")
        ]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(
            _row(track_name="Static", artist_names="Totally Different Artist", album_name="Waveforms")
        )
        assert tier == 3
        assert entry["path"] == "/crate/static.mp3"

    def test_tier3_duration_is_a_soft_tiebreak_among_album_matching_candidates(self):
        # two entries share the queried title AND album (so both pass
        # tier 3's predicate) but differ in length - duration should pick
        # the closer one among them, not just first-match-wins.
        catalog = [
            _entry(title="Static", artist="Nova", album="Waveforms", length=200.0, path="/crate/static_v1.mp3"),
            _entry(title="Static", artist="Kade", album="Waveforms", length=210.0, path="/crate/static_v2.mp3"),
        ]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(
            _row(
                track_name="Static", artist_names="Someone Completely Unrelated",
                album_name="Waveforms", duration_ms=201000,
            )
        )
        assert tier == 3
        assert entry["path"] == "/crate/static_v1.mp3"

    def test_tier3_falls_back_to_closest_duration_even_outside_tolerance(self):
        # same two candidates as above, but the queried duration is far
        # outside tier 3's 3s tolerance for BOTH - per the module docstring's
        # correction #3, duration is never a hard reject: the closest
        # candidate should still be returned rather than refusing outright.
        catalog = [
            _entry(title="Static", artist="Nova", album="Waveforms", length=200.0, path="/crate/static_v1.mp3"),
            _entry(title="Static", artist="Kade", album="Waveforms", length=210.0, path="/crate/static_v2.mp3"),
        ]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(
            _row(
                track_name="Static", artist_names="Someone Completely Unrelated",
                album_name="Waveforms", duration_ms=500000,
            )
        )
        assert tier == 3
        assert entry["path"] == "/crate/static_v2.mp3"  # 210s is closer to 500s than 200s is

    def test_tier4_core_title_rescues_local_feat_clause_suffix(self):
        # local file kept a "(feat. Mia)" suffix spotify's title doesn't
        # have, so the exact-title key differs and tiers 1-3 (which all key
        # off the exact by_title bucket) find nothing. tier 4's core-title
        # index (feat. clause stripped) picks it up instead.
        catalog = [_entry(title="Golden Hour (feat. Mia)", artist="Nova", path="/crate/golden.mp3")]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(_row(track_name="Golden Hour", artist_names="Nova"))
        assert tier == 4
        assert entry["path"] == "/crate/golden.mp3"

    def test_tier5_fuzzy_title_within_ratio_and_duration(self):
        # one-character typo, same 4-char prefix, close duration - too far
        # off for tiers 1-4 (all require an exact or core-stripped title key
        # match, which a typo breaks), close enough for tier 5's fuzzy ratio.
        catalog = [
            _entry(title="Broken Mirror", artist="Nova", length=200.0, path="/crate/broken.mp3")
        ]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(
            _row(track_name="Brokn Mirror", artist_names="Someone Else", duration_ms=200000)
        )
        assert tier == 5
        assert entry["path"] == "/crate/broken.mp3"

    def test_tier5_does_not_fire_below_ratio_threshold(self):
        catalog = [_entry(title="Broken Mirror", artist="Nova", path="/crate/broken.mp3")]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(_row(track_name="Broken Glass", artist_names="Nova"))
        assert entry is None
        assert tier is None

    def test_tier6a_symbol_title_exact_raw_match_with_artist_anchor(self):
        catalog = [
            _entry(title="$$$", artist="Nova", album="Vibes", length=150.0, path="/crate/symbol.mp3")
        ]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(_row(track_name="$$$", artist_names="Nova", duration_ms=150000))
        assert tier == 6
        assert entry["path"] == "/crate/symbol.mp3"

    def test_tier6b_symbol_title_falls_back_to_album_and_track_position(self):
        # raw title doesn't match exactly ("!!!!" vs "????"), so 6a misses -
        # falls through to 6b's (album, track_number) position match.
        catalog = [
            _entry(
                title="!!!!", artist="Nova", album="Vibes", track=3, length=140.0,
                path="/crate/pos.mp3",
            )
        ]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(
            _row(
                track_name="????", artist_names="Someone Else", album_name="Vibes",
                track_number=3, duration_ms=140000,
            )
        )
        assert tier == 6
        assert entry["path"] == "/crate/pos.mp3"

    def test_no_tier_matches_returns_none_none(self):
        catalog = [_entry(title="Something", artist="Someone", path="/crate/x.mp3")]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(_row(track_name="Completely Unrelated", artist_names="Nobody At All"))
        assert entry is None
        assert tier is None


class TestSymbolTitleIndexExclusion:
    """Regression coverage for drift point #6 in the module docstring: a
    symbol-only/blank local title must never surface via the normal
    by_title index, or a symbol query could wrongly cross-match another
    symbol-titled track by artist alone instead of going through tier 6's
    dedicated (and more tightly anchored) path."""

    def test_by_title_never_registers_the_empty_key(self):
        catalog = [_entry(title="$$$", artist="Nova", path="/crate/a.mp3")]
        idx = MatchIndex(catalog)
        assert idx.by_title.get("") in (None, [])

    def test_two_different_symbol_titles_do_not_cross_match_on_artist_alone(self):
        # two distinct symbol-titled tracks by the same artist - a query
        # for one must not resolve to the other just because both titles
        # normalize to "" and share an artist.
        catalog = [
            _entry(title="$$$", artist="Nova", album="Album One", track=1, length=100.0, path="/crate/one.mp3"),
            _entry(title="!!!", artist="Nova", album="Album Two", track=1, length=200.0, path="/crate/two.mp3"),
        ]
        idx = MatchIndex(catalog)
        entry, tier = idx.match(
            _row(track_name="$$$", artist_names="Nova", album_name="Album One", duration_ms=100000)
        )
        assert entry["path"] == "/crate/one.mp3"


class TestRowFieldFallbacks:
    def test_accepts_alternate_column_names(self):
        catalog = [_entry(title="Fallback Song", artist="Nova", path="/crate/f.mp3")]
        idx = MatchIndex(catalog)
        # 'title'/'artist' instead of the real CSV columns track_name/artist_names
        entry, tier = idx.match({"title": "Fallback Song", "artist": "Nova"})
        assert entry is not None
        assert entry["path"] == "/crate/f.mp3"


class TestRowDurationSeconds:
    def test_prefers_duration_ms(self):
        assert _row_duration_seconds({"duration_ms": 245000}) == 245.0

    def test_falls_back_to_seconds_field(self):
        assert _row_duration_seconds({"length": 180}) == 180.0

    def test_returns_none_when_nothing_present(self):
        assert _row_duration_seconds({}) is None


class TestRowTrackNumber:
    def test_parses_x_of_y_format(self):
        assert _row_track_number({"track_number": "3/12"}) == 3

    def test_returns_none_for_unparseable_value(self):
        assert _row_track_number({"track_number": "not a number"}) is None


class TestTierName:
    def test_known_tiers_have_labels(self):
        assert tier_name(1) == "exact_title_primary_artist"
        assert tier_name(6) == "symbol_title"

    def test_unknown_tier_falls_back_to_generic_label(self):
        assert tier_name(999) == "tier_999"


class TestMatchRows:
    def test_unmatched_row_gets_unmatched_result(self):
        idx = MatchIndex([])
        results = match_rows([_row(track_name="Nothing Here", artist_names="Nobody")], index=idx)
        assert len(results) == 1
        assert results[0]["tier"] == "unmatched"
        assert results[0]["path"] is None

    def test_caches_by_track_id_across_rows(self):
        catalog = [_entry(title="Echoes", artist="Nova", path="/crate/echo.mp3")]
        idx = MatchIndex(catalog)
        rows = [
            _row(track_name="Echoes", artist_names="Nova", track_id="tid1"),
            # shares track_id with the row above, but its own title/artist
            # would NOT resolve on its own - proves the cache is what's
            # being used, not a fresh (and lucky) re-match
            _row(track_name="Something Completely Different", artist_names="Nobody", track_id="tid1"),
        ]
        results = match_rows(rows, index=idx)
        assert results[0]["path"] == results[1]["path"] == "/crate/echo.mp3"

    def test_preserves_input_order(self):
        catalog = [
            _entry(title="First", artist="A", path="/crate/first.mp3"),
            _entry(title="Second", artist="B", path="/crate/second.mp3"),
        ]
        idx = MatchIndex(catalog)
        rows = [_row(track_name="Second", artist_names="B"), _row(track_name="First", artist_names="A")]
        results = match_rows(rows, index=idx)
        assert [r["row"]["track_name"] for r in results] == ["Second", "First"]

    def test_requires_catalog_or_index(self):
        with pytest.raises(ValueError):
            match_rows([_row(track_name="X", artist_names="Y")])

    def test_builds_its_own_index_from_a_raw_catalog(self):
        catalog = [_entry(title="Solo Track", artist="Artist", path="/crate/solo.mp3")]
        results = match_rows([_row(track_name="Solo Track", artist_names="Artist")], catalog=catalog)
        assert results[0]["path"] == "/crate/solo.mp3"
