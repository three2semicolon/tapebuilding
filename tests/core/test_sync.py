"""Tests for core.sync - TEST_PLANS.md 'core/sync.py' section.

SKELETON, mostly. Documented signature from PACKAGE_OVERVIEW.md:
`run_sync(names=None, covers=False, verbose=False, playlists_path=None,
archive_path=None, exports_dir=None)`.
"""
import pytest


@pytest.mark.skip(reason="core/sync.py source not yet reviewed - see module docstring")
def test_run_sync_forwards_to_build_playlists_with_apply_and_rescrape_true():
    """run_sync() is documented as the `playlists --apply --rescrape`
    flow promoted to a function - assert it calls build_playlists with
    apply=True, rescrape=True (or equivalent) rather than reimplementing
    any of that logic itself."""
    pass


@pytest.mark.skip(reason="core/sync.py source not yet reviewed")
def test_no_dry_run_mode_of_its_own():
    """run_sync() has no dry-run of its own by design - previewing is
    documented as calling build_playlists(apply=False, ...) directly.
    Worth a test confirming that actually produces the same preview
    output run_sync() would, not just that it's documented as the way."""
    pass


@pytest.mark.skip(reason="core/sync.py source not yet reviewed")
def test_names_param_scopes_to_specific_playlists():
    pass


@pytest.mark.skip(reason="core/sync.py source not yet reviewed")
def test_covers_flag_forwards_to_build_playlists():
    pass