"""Tests for tapedeck.copy - TEST_PLANS.md 'tapedeck/copy.py' section.

SKELETON ONLY - tapedeck/copy.py source not yet reviewed.
"""
import pytest


@pytest.mark.skip(reason="tapedeck/copy.py source not yet reviewed")
def test_stage_copies_by_default():
    pass


@pytest.mark.skip(reason="tapedeck/copy.py source not yet reviewed")
def test_stage_hardlinks_with_link_flag_same_volume_only():
    pass


@pytest.mark.skip(reason="tapedeck/copy.py source not yet reviewed")
def test_stage_skips_existing_unless_overwrite():
    pass


@pytest.mark.skip(reason="tapedeck/copy.py source not yet reviewed")
def test_unstage_refcounted_shared_track_survives_first_unload():
    """Load two playlists sharing a track, unload one - the shared track
    should NOT be removed. Unload the second - now it should be."""
    pass


@pytest.mark.skip(reason="tapedeck/copy.py source not yet reviewed")
def test_unstage_playlist_refcount_does_not_protect_independently_loaded_track():
    """Documented sharp edge: a track independently loaded via
    `load album`/`load song` and also referenced by an unloaded playlist
    should NOT be protected by playlist refcounting (scoped to playlists
    only)."""
    pass


@pytest.mark.skip(reason="tapedeck/copy.py source not yet reviewed")
def test_unstage_prunes_empty_parent_directories():
    pass