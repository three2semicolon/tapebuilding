"""Tests for tapedeck.resolve - TEST_PLANS.md 'tapedeck/resolve.py'
section.

SKELETON ONLY - tapedeck/resolve.py source not yet reviewed.
"""
import pytest


@pytest.mark.skip(reason="tapedeck/resolve.py source not yet reviewed")
@pytest.mark.parametrize("kind,spec_is_path", [
    ("album", True),
    ("soundtrack", False),
    ("playlist", False),
])
def test_need_index_for_skips_when_not_needed(kind, spec_is_path):
    pass


@pytest.mark.skip(reason="tapedeck/resolve.py source not yet reviewed")
def test_need_index_for_true_for_album_by_name():
    pass


@pytest.mark.skip(reason="tapedeck/resolve.py source not yet reviewed")
@pytest.mark.parametrize("kind", ["album", "song", "soundtrack", "playlist"])
def test_resolve_each_kind_returns_expected_buckets(kind):
    """folders, files, m3u8, warnings - per PACKAGE_OVERVIEW.md."""
    pass