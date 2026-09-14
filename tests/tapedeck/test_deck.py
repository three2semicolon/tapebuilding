"""Tests for tapedeck.deck - TEST_PLANS.md 'tapedeck/deck.py' section.

SKELETON ONLY - tapedeck/deck.py source not yet reviewed.
"""
import pytest


@pytest.mark.skip(reason="tapedeck/deck.py source not yet reviewed")
def test_maybe_index_only_builds_when_need_index_for_says_to():
    pass


@pytest.mark.skip(reason="tapedeck/deck.py source not yet reviewed")
def test_unload_tapedeck_does_not_raise_attributeerror_on_reindex_kwarg():
    """Regression test for a documented pre-refactor bug: unload_tapedeck()
    used to unconditionally read a possibly-undefined `reindex` arg. Make
    sure it doesn't come back."""
    pass


@pytest.mark.skip(reason="tapedeck/deck.py source not yet reviewed")
def test_playlists_root_returns_none_gracefully_when_playlists_path_unset():
    """load/unload of album/song/soundtrack shouldn't require
    PLAYLISTS_PATH to be set at all."""
    pass


@pytest.mark.skip(reason="tapedeck/deck.py source not yet reviewed")
def test_fmt_size_human_readable():
    pass