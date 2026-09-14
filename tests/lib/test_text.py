"""Tests for lib.text - TEST_PLANS.md 'lib/text.py' section.

Written against the actual current source. lib.text's own module docstring
carries an inline `_run_sanity_checks()` (`python -m lib.text`) covering
much of the same ground informally - these are the same cases, as real
pytest assertions with per-behavior names so a regression points at the
specific claim that broke instead of one big assert block.
"""
from lib.text import (
    normalize_key,
    normalize_title,
    strip_feat_clause,
    split_artists,
    primary_artist,
)


class TestNormalizeKey:
    def test_lowercases_and_strips_punctuation(self):
        assert normalize_key(" Hello, World! ") == "helloworld"

    def test_removes_whitespace_entirely_not_just_collapses_it(self):
        # normalize_key strips every non-alphanumeric char, including
        # internal whitespace - it doesn't collapse runs to a single space
        # the way normalize_title does.
        assert normalize_key("Song   Title") == "songtitle"

    def test_empty_and_none_return_empty_string(self):
        assert normalize_key("") == ""
        assert normalize_key(None) == ""

    def test_symbol_only_string_collapses_to_empty(self):
        assert normalize_key("$$$") == ""
        assert normalize_key("!!!") == ""


class TestNormalizeTitle:
    def test_strips_feat_clause_and_everything_after_it(self):
        assert normalize_title("Song feat. Other Artist") == normalize_title("Song")
        assert normalize_title("Song Ft. Other") == normalize_title("Song")
        assert normalize_title("Song featuring Other") == normalize_title("Song")

    def test_strips_parenthetical_content(self):
        assert normalize_title("Song (Radio Edit)") == normalize_title("Song")

    def test_combines_feat_stripping_and_parenthetical_stripping(self):
        assert normalize_title("Song (feat. Other) (Remix)") == normalize_title("Song")

    def test_symbol_only_title_collapses_to_empty(self):
        # this is the case lib.catalog.matcher's tier 6 depends on to know
        # a title has "nothing left" and needs the symbol-title fallback
        # path instead of the normal by_title index.
        assert normalize_title("$$$") == ""


class TestStripFeatClause:
    """Conservative sibling of normalize_title: removes ONLY a bracketed
    feat./ft./featuring/with/vs credit, leaves everything else - including
    other parentheticals - intact. Used ahead of normalize_key() when
    matching a local file tag that kept a "(feat. X)" suffix, per
    lib.catalog.matcher's tier 4."""

    def test_removes_bracketed_feat_credit(self):
        assert strip_feat_clause("Title (feat. X)") == "Title"
        assert strip_feat_clause("Title [ft. X]") == "Title"

    def test_removes_with_and_vs_credits_too(self):
        assert strip_feat_clause("Title (with X)") == "Title"
        assert strip_feat_clause("Title (vs X)") == "Title"

    def test_preserves_non_feat_parentheticals(self):
        # the key difference from normalize_title, which would strip this too
        assert strip_feat_clause("Title (Remix)") == "Title (Remix)"

    def test_noop_when_nothing_to_strip(self):
        assert strip_feat_clause("Title") == "Title"

    def test_empty_string(self):
        assert strip_feat_clause("") == ""

    def test_feeds_normalize_key_to_produce_a_clean_lookup_key(self):
        assert normalize_key(strip_feat_clause("Title (feat. X)")) == normalize_key("Title")


class TestPrimaryArtist:
    def test_from_ampersand_form(self):
        assert primary_artist("A, B & C") == "A"

    def test_from_feat_form(self):
        assert primary_artist("A feat. B") == "A"

    def test_empty_string_returns_empty_string(self):
        assert primary_artist("") == ""


class TestSplitArtists:
    def test_handles_comma_ampersand_slash_x_vs_feat(self):
        assert split_artists("A, B & C") == ["A", "B", "C"]
        assert split_artists("A / B") == ["A", "B"]
        assert split_artists("A x B") == ["A", "B"]
        assert split_artists("A vs B") == ["A", "B"]
        assert split_artists("A feat. B") == ["A", "B"]
        assert split_artists("A ft. B") == ["A", "B"]
        assert split_artists("A featuring B") == ["A", "B"]

    def test_solo_artist_is_single_element_list(self):
        assert split_artists("Solo Artist") == ["Solo Artist"]

    def test_empty_string_is_empty_list(self):
        assert split_artists("") == []

    def test_does_not_split_on_bare_and(self):
        """Deliberate divergence from organize.normalize_artists' beets
        plugin (which DOES split on 'and') - see PACKAGE_OVERVIEW.md's
        lib/text.py section, and lib/text.py's own inline sanity check.
        This test protects that decision from being "fixed" into
        consistency later - don't change the expected value here without
        checking PACKAGE_OVERVIEW.md first.
        """
        assert split_artists("A and B") == ["A and B"]
