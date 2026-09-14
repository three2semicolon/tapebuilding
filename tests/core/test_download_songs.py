"""Tests for core.download_songs - TEST_PLANS.md 'core/download_songs.py'
section.

Mostly SKELETON: I have the documented signature from PACKAGE_OVERVIEW.md
(`run_download_songs(source=None, apply=False, archive_path_opt=None,
drop=None, only=None, format='mp3', bitrate='320k', verbose=False)`) but
not the module's real source, so I don't know the exact names it imports
download_spotify/run_import/build_playlists under (needed to know what
to monkeypatch). Fill in the `monkeypatch.setattr(...)` targets once
you've confirmed them against the real file.
"""
import pytest


@pytest.mark.skip(reason="core/download_songs.py source not yet reviewed - see module docstring")
def test_resolve_source_passes_through_existing_file_or_dir():
    pass


@pytest.mark.skip(reason="core/download_songs.py source not yet reviewed")
def test_resolve_source_writes_bare_spotify_url_to_temp_txt():
    pass


@pytest.mark.skip(reason="core/download_songs.py source not yet reviewed")
def test_dry_run_calls_each_step_in_its_own_no_op_mode_not_skipped():
    """The documented, deliberate behavior: apply=False should still call
    download_spotify(validate_only=True), run_import(dry_run=True),
    build_playlists(apply=False) - NOT skip the steps outright. This is
    the single most important behavior to pin down here, since it's an
    explicit departure from the old subprocess pipeline's dry-run (which
    ran nothing at all)."""
    pass


@pytest.mark.skip(reason="core/download_songs.py source not yet reviewed")
def test_only_flag_runs_specified_steps_in_fixed_order():
    """--only download --only playlists (given in that order on the CLI)
    should still run download -> import -> playlists order if import
    were also included - fixed order regardless of flag order, per
    README.md."""
    pass


@pytest.mark.skip(reason="core/download_songs.py source not yet reviewed")
def test_return_shape_on_success():
    """{'steps': [{'step','ok','error','skipped'}, ...], 'ok': True}"""
    pass


@pytest.mark.skip(reason="core/download_songs.py source not yet reviewed")
def test_return_shape_on_injected_step_failure():
    """A failing step should produce ok=False overall, with the specific
    failing step's dict carrying an 'error' value."""
    pass


@pytest.mark.skip(reason="core/download_songs.py source not yet reviewed")
def test_verbose_forwards_to_download_spotify_debug_not_a_separate_flag():
    """download.cli's own `spotify` subcommand has no separate --verbose,
    only --debug - run_download_songs's verbose param should map onto
    download_spotify(debug=verbose)."""
    pass