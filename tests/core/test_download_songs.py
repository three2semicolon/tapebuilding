"""Tests for core.download_songs - TEST_PLANS.md 'core/download_songs.py'
section.

The three domain steps (download.spotify_download.download_spotify,
organize.beets_import.run_import, playlists.build.build_playlists) are
mocked throughout - each already has its own real tests in its own
package. What matters here is core.download_songs's own wiring: is each
step actually invoked (in its own no-op mode on a dry run, never
skipped), in the fixed order, with the documented kwargs, and does the
{'steps': [...], 'ok': ...} summary come out right on success, on a
falsy step result, and on a raised exception.
"""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import core.download_songs as ds_mod
from core.download_songs import _resolve_source, run_download_songs


SPOTIFY_URL = "https://open.spotify.com/playlist/abc123"


# --- _resolve_source -----------------------------------------------------------

def test_resolve_source_passes_through_existing_file_or_dir(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("http://example.com/track\n")
    path, tmp_to_unlink = _resolve_source(str(f))
    assert path == str(f)
    assert tmp_to_unlink is None

    d = tmp_path / "export_dir"
    d.mkdir()
    path, tmp_to_unlink = _resolve_source(str(d))
    assert path == str(d)
    assert tmp_to_unlink is None


def test_resolve_source_writes_bare_spotify_url_to_temp_txt():
    path, tmp_to_unlink = _resolve_source(SPOTIFY_URL)
    try:
        assert path == tmp_to_unlink          # caller is told to clean up exactly this file
        assert path.endswith(".txt")
        with open(path, encoding='utf-8') as fh:
            assert fh.read() == SPOTIFY_URL + "\n"
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


def test_resolve_source_recognizes_spotify_uri_prefix():
    path, tmp_to_unlink = _resolve_source("spotify:track:abc123")
    try:
        assert path is not None
        assert path == tmp_to_unlink
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


def test_resolve_source_returns_none_for_bad_input():
    assert _resolve_source(None) == (None, None)
    assert _resolve_source("not-a-path-and-not-a-url") == (None, None)


# --- run_download_songs: fixtures -----------------------------------------------

@pytest.fixture
def mocks(monkeypatch):
    download_mock = MagicMock(return_value=True)
    import_mock = MagicMock(return_value=True)
    playlists_mock = MagicMock(return_value=True)
    monkeypatch.setattr(ds_mod, "download_spotify", download_mock)
    monkeypatch.setattr(ds_mod, "run_import", import_mock)
    monkeypatch.setattr(ds_mod, "build_playlists", playlists_mock)
    return SimpleNamespace(download=download_mock, import_=import_mock, playlists=playlists_mock)


# --- dry run: each step runs for real, in its own no-op mode -------------------

def test_dry_run_calls_each_step_in_its_own_no_op_mode_not_skipped(tmp_path, mocks):
    drop = tmp_path / "drop"
    drop.mkdir()

    result = run_download_songs(
        source=SPOTIFY_URL,
        apply=False,
        archive_path_opt=str(tmp_path),
        drop=str(drop),
    )

    mocks.download.assert_called_once()
    assert mocks.download.call_args.kwargs['validate_only'] is True
    assert mocks.download.call_args.kwargs['debug'] is False

    mocks.import_.assert_called_once()
    assert mocks.import_.call_args.kwargs['dry_run'] is True

    mocks.playlists.assert_called_once()
    assert mocks.playlists.call_args.kwargs['apply'] is False
    assert mocks.playlists.call_args.kwargs['reindex'] is True

    # none of the three steps were skipped just because this was a dry run
    assert all(not s['skipped'] for s in result['steps'])
    assert result['ok'] is True


# --- --only: fixed step order regardless of flag order --------------------------

def test_only_flag_runs_specified_steps_in_fixed_order(tmp_path, mocks):
    call_order = []
    mocks.download.side_effect = lambda **k: call_order.append('download') or True
    mocks.playlists.side_effect = lambda **k: call_order.append('playlists') or True

    result = run_download_songs(
        source=SPOTIFY_URL,
        apply=True,
        archive_path_opt=str(tmp_path),
        only=['playlists', 'download'],   # given out of the fixed order
    )

    assert call_order == ['download', 'playlists']
    mocks.import_.assert_not_called()
    assert [s['step'] for s in result['steps']] == ['download', 'playlists']


# --- return shape -----------------------------------------------------------------

def test_return_shape_on_success(tmp_path, mocks):
    result = run_download_songs(
        source=SPOTIFY_URL, apply=True, archive_path_opt=str(tmp_path), only=['download'],
    )
    assert result == {
        'steps': [{'step': 'download', 'ok': True, 'error': None, 'skipped': False}],
        'ok': True,
    }


def test_return_shape_on_injected_exception_failure(tmp_path, mocks):
    drop = tmp_path / "drop"
    drop.mkdir()
    mocks.import_.side_effect = RuntimeError("boom")

    result = run_download_songs(
        archive_path_opt=str(tmp_path), drop=str(drop), only=['import'],
    )
    assert result == {
        'steps': [{'step': 'import', 'ok': False, 'error': 'boom', 'skipped': False}],
        'ok': False,
    }


def test_return_shape_on_falsy_step_result_without_exception(tmp_path, mocks):
    """A step can fail "cleanly" (returns False, no exception) - the
    summary should still flip 'ok' to False even with no 'error' string."""
    mocks.download.return_value = False
    result = run_download_songs(
        source=SPOTIFY_URL, apply=True, archive_path_opt=str(tmp_path), only=['download'],
    )
    assert result == {
        'steps': [{'step': 'download', 'ok': False, 'error': None, 'skipped': False}],
        'ok': False,
    }


def test_download_step_without_source_records_error_and_skips_the_call(tmp_path, mocks):
    result = run_download_songs(apply=True, archive_path_opt=str(tmp_path), only=['download'])
    mocks.download.assert_not_called()
    assert result == {
        'steps': [{
            'step': 'download', 'ok': False, 'skipped': False,
            'error': "the download step needs a source (url file/dir, or a single spotify url)",
        }],
        'ok': False,
    }


def test_import_step_skipped_when_drop_dir_missing(tmp_path, mocks):
    """A skipped step doesn't count against overall 'ok'."""
    missing_drop = tmp_path / "does-not-exist"
    result = run_download_songs(
        archive_path_opt=str(tmp_path), drop=str(missing_drop), only=['import'],
    )
    mocks.import_.assert_not_called()
    assert result == {
        'steps': [{'step': 'import', 'ok': True, 'error': None, 'skipped': True}],
        'ok': True,
    }


# --- verbose -> debug mapping ------------------------------------------------------

def test_verbose_forwards_to_download_spotify_debug_not_a_separate_flag(tmp_path, mocks):
    drop = tmp_path / "drop"
    drop.mkdir()
    run_download_songs(
        source=SPOTIFY_URL, apply=True, archive_path_opt=str(tmp_path),
        drop=str(drop), verbose=True,
    )
    assert mocks.download.call_args.kwargs['debug'] is True
    assert 'verbose' not in mocks.download.call_args.kwargs
    assert mocks.import_.call_args.kwargs['verbose'] is True
    assert mocks.playlists.call_args.kwargs['verbose'] is True


# --- misc wiring --------------------------------------------------------------------

def test_default_drop_is_unorganized_under_crate(tmp_path, mocks, monkeypatch):
    monkeypatch.setattr(ds_mod, "archive_path", lambda: str(tmp_path))
    run_download_songs(source=SPOTIFY_URL, apply=True, only=['download'])
    assert mocks.download.call_args.kwargs['output_dir'] == str(tmp_path / "unorganized")


def test_source_tmp_file_cleaned_up_after_run(tmp_path, mocks):
    run_download_songs(
        source=SPOTIFY_URL, apply=True, archive_path_opt=str(tmp_path), only=['download'],
    )
    written_path = mocks.download.call_args.kwargs['url_file']
    assert not os.path.exists(written_path)
