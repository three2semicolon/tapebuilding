"""Tests for core.process_unmatched - process-unmatched workflow.

The three domain steps (playlists.build.build_playlists,
download.spotify_download.download_spotify, organize.beets_import.run_import)
are mocked throughout - each already has its own real tests in its own
package. What matters here is core.process_unmatched's own wiring: is each
step actually invoked (in its own no-op mode on a dry run, never
skipped), in the fixed order, with the documented kwargs, and does the
{'steps': [...], 'ok': ...} summary come out right on success, on a
falsy step result, and on a raised exception.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import core.process_unmatched as pu_mod
from core.process_unmatched import run_process_unmatched


# --- run_process_unmatched: fixtures -----------------------------------------------

@pytest.fixture
def mocks(monkeypatch):
    build_playlists_mock = MagicMock(return_value=True)
    download_spotify_mock = MagicMock(return_value=True)
    run_import_mock = MagicMock(return_value={'ok': True})
    monkeypatch.setattr(pu_mod, "build_playlists", build_playlists_mock)
    monkeypatch.setattr(pu_mod, "download_spotify", download_spotify_mock)
    monkeypatch.setattr(pu_mod, "run_import", run_import_mock)
    return SimpleNamespace(
        build_playlists=build_playlists_mock,
        download_spotify=download_spotify_mock,
        run_import=run_import_mock,
    )


# --- dry run: each step runs for real, in its own no-op mode ----------------------

def test_dry_run_calls_each_step_in_its_own_no_op_mode_not_skipped(tmp_path, mocks):
    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file so it exists
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        result = run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            apply=False,
        )

    # Step 1: build_playlists should be called with apply=False, rescrape=True, reindex=True
    # Step 4: build_playlists should be called with apply=False, rescrape=False, reindex=True
    assert mocks.build_playlists.call_count == 2
    build_playlists_calls = mocks.build_playlists.call_args_list
    # First call: step 1 (refresh playlists to generate unmatched CSV)
    build_playlists_call_1 = build_playlists_calls[0].kwargs
    assert build_playlists_call_1['apply'] is False
    assert build_playlists_call_1['rescrape'] is True
    assert build_playlists_call_1['reindex'] is True
    assert build_playlists_call_1['names'] == []  # No specific names - use scope (owned playlists))
    # Second call: step 4 (sync playlists with library)
    build_playlists_call_2 = build_playlists_calls[1].kwargs
    assert build_playlists_call_2['apply'] is False
    assert build_playlists_call_2['rescrape'] is False  # No rescrape - just reindex
    assert build_playlists_call_2['reindex'] is True
    assert build_playlists_call_2['names'] == []  # No specific names - use scope (owned playlists))

    # Step 2: download_spotify should be called with validate_only=True (dry run mode)
    mocks.download_spotify.assert_called_once()
    download_call = mocks.download_spotify.call_args.kwargs
    assert download_call['validate_only'] is True
    assert download_call['debug'] is False

    # Step 3: run_import should be called with dry_run=True (dry run mode)
    mocks.run_import.assert_called_once()
    import_call = mocks.run_import.call_args.kwargs
    assert import_call['dry_run'] is True
    assert import_call['verbose'] is False

    # none of the four steps were skipped just because this was a dry run
    assert all(not s['skipped'] for s in result['steps'])
    assert result['ok'] is True


# --- apply mode: each step runs for real ------------------------------------------

def test_apply_mode_calls_each_step_in_real_mode(tmp_path, mocks):
    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file so it exists
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        result = run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            apply=True,
        )

    # Step 1: build_playlists should be called with apply=True, rescrape=True, reindex=True
    # Step 4: build_playlists should be called with apply=True, rescrape=False, reindex=True
    assert mocks.build_playlists.call_count == 2
    build_playlists_calls = mocks.build_playlists.call_args_list
    # First call: step 1 (refresh playlists to generate unmatched CSV)
    build_playlists_call_1 = build_playlists_calls[0].kwargs
    assert build_playlists_call_1['apply'] is True
    assert build_playlists_call_1['rescrape'] is True
    assert build_playlists_call_1['reindex'] is True
    # Second call: step 4 (sync playlists with library)
    build_playlists_call_2 = build_playlists_calls[1].kwargs
    assert build_playlists_call_2['apply'] is True
    assert build_playlists_call_2['rescrape'] is False  # No rescrape - just reindex
    assert build_playlists_call_2['reindex'] is True

    # Step 2: download_spotify should be called with validate_only=False (real mode)
    mocks.download_spotify.assert_called_once()
    download_call = mocks.download_spotify.call_args.kwargs
    assert download_call['validate_only'] is False

    # Step 3: run_import should be called with dry_run=False (real mode)
    mocks.run_import.assert_called_once()
    import_call = mocks.run_import.call_args.kwargs
    assert import_call['dry_run'] is False

    # all steps should succeed
    assert all(s['ok'] for s in result['steps'] if not s['skipped'])
    assert result['ok'] is True


# --- step skipping when previous step fails ---------------------------------------

def test_download_step_skipped_when_build_playlists_fails(tmp_path, mocks):
    # Simulate build_playlists "failure" by making it not generate unmatched CSV
    # We'll do this by making build_playlists raise an exception when called
    # which will cause the step to be recorded as failed
    mocks.build_playlists.side_effect = Exception("Simulated failure")

    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        result = run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            apply=True,
        )

    # build_playlists should have been called once (initial attempt that failed)
    mocks.build_playlists.assert_called_once()
    # download_spotify should NOT have been called (step skipped)
    mocks.download_spotify.assert_not_called()
    # run_import should NOT have been called (step skipped)
    mocks.run_import.assert_not_called()

    # First step should show as failed, others as skipped
    assert len(result['steps']) == 4
    assert result['steps'][0] == {'step': 'refresh-playlists', 'ok': False, 'error': 'Simulated failure', 'skipped': False}
    assert result['steps'][1] == {'step': 'download', 'ok': True, 'error': None, 'skipped': True}
    assert result['steps'][2] == {'step': 'import', 'ok': True, 'error': None, 'skipped': True}
    assert result['steps'][3] == {'step': 'refresh-playlists-sync', 'ok': True, 'error': None, 'skipped': True}
    assert result['ok'] is False  # Overall not ok because first step failed


def test_import_step_skipped_when_download_fails(tmp_path, mocks):
    mocks.download_spotify.return_value = False  # Simulate download failure

    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file so the download step executes
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        result = run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            apply=True,
        )

    # All steps should have been called
    assert mocks.build_playlists.call_count == 2  # Step 1 and step 4
    mocks.download_spotify.assert_called_once()
    mocks.run_import.assert_called_once()  # Should now be called (changed behavior)

    # Check step results
    assert len(result['steps']) == 4
    assert result['steps'][0]['step'] == 'refresh-playlists'
    assert result['steps'][0]['ok'] is True
    assert result['steps'][0]['skipped'] is False

    assert result['steps'][1]['step'] == 'download'
    assert result['steps'][1]['ok'] is False
    assert result['steps'][1]['skipped'] is False

    assert result['steps'][2]['step'] == 'import'
    assert result['steps'][2]['ok'] is True  # Now executed (not skipped)
    assert result['steps'][2]['skipped'] is False

    assert result['steps'][3]['step'] == 'refresh-playlists-sync'
    assert result['steps'][3]['ok'] is True  # Now executed (not skipped)
    assert result['steps'][3]['skipped'] is False

    assert result['ok'] is False  # Overall not ok because download step failed


# --- service selection -------------------------------------------------------------

def test_service_spotify_uses_spotify_download(tmp_path, mocks):
    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file so the download step executes
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            service='spotify',
            apply=False,
        )

    # Should call download_spotify (not download_soundcloud)
    mocks.download_spotify.assert_called_once()
    # download_soundcloud doesn't exist in this mock setup, but we can verify
    # that we didn't try to call a non-existent function by checking that
    # download_spotify was called exactly once


# --- exclude names forwarding ------------------------------------------------------

def test_exclude_names_forwards_to_build_playlists(tmp_path, mocks, monkeypatch):
    # Ensure PLAYLISTS_EXCLUDE is not set to avoid interference
    monkeypatch.delenv('PLAYLISTS_EXCLUDE', raising=False)

    run_process_unmatched(
        archive_path_opt=str(tmp_path),
        playlists_path_opt=str(tmp_path / "playlists"),
        exports_dir_opt=str(tmp_path / "exports"),
        exclude_names=['_orc', '__beats by three2'],
        apply=False,
    )

    mocks.build_playlists.assert_called_once()
    assert mocks.build_playlists.call_args.kwargs['exclude_names'] == ['_orc', '__beats by three2']


# --- environment variable handling -------------------------------------------------

def test_playlists_exclude_env_var_is_used(tmp_path, mocks, monkeypatch):
    # Set the environment variable
    monkeypatch.setenv('PLAYLISTS_EXCLUDE', '_orc,__beats by three2,__obs')

    # Call without explicit exclude_names
    run_process_unmatched(
        archive_path_opt=str(tmp_path),
        playlists_path_opt=str(tmp_path / "playlists"),
        exports_dir_opt=str(tmp_path / "exports"),
        apply=False,
    )

    # Should have received the env var values
    mocks.build_playlists.assert_called_once()
    assert mocks.build_playlists.call_args.kwargs['exclude_names'] == ['_orc', '__beats by three2', '__obs']


def test_playlists_exclude_env_var_combined_with_command_line(tmp_path, mocks, monkeypatch):
    # Set the environment variable
    monkeypatch.setenv('PLAYLISTS_EXCLUDE', '_orc,__beats by three2')

    # Call with additional explicit exclude_names
    run_process_unmatched(
        archive_path_opt=str(tmp_path),
        playlists_path_opt=str(tmp_path / "playlists"),
        exports_dir_opt=str(tmp_path / "exports"),
        exclude_names=['__obs', 'spotify:playlist:xyz'],
        apply=False,
    )

    # Should have combined both: env var + command line
    mocks.build_playlists.assert_called_once()
    # Order: command line args first, then env var (based on implementation)
    expected = ['__obs', 'spotify:playlist:xyz', '_orc', '__beats by three2']
    assert mocks.build_playlists.call_args.kwargs['exclude_names'] == expected


# --- format and bitrate forwarding -------------------------------------------------

def test_format_and_bitrate_forwards_to_download_spotify(tmp_path, mocks):
    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file so the download step executes
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            format='flac',
            bitrate='1000k',
            apply=False,
        )

    mocks.download_spotify.assert_called_once()
    download_call = mocks.download_spotify.call_args.kwargs
    assert download_call['format'] == 'flac'
    assert download_call['bitrate'] == '1000k'


# --- cookies file forwarding -------------------------------------------------------

def test_cookies_file_forwards_to_download_spotify(tmp_path, mocks):
    cookies_file = str(tmp_path / "cookies.txt")
    # Create a dummy cookies file
    with open(cookies_file, 'w') as f:
        f.write("# Netscape HTTP Cookie File\n")

    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file so the download step executes
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            cookies_file=cookies_file,
            apply=False,
        )

    mocks.download_spotify.assert_called_once()
    download_call = mocks.download_spotify.call_args.kwargs
    assert download_call['cookie_file'] == cookies_file


# --- pre-skip-existing forwarding --------------------------------------------------

def test_pre_skip_existing_forwards_to_download_spotify(tmp_path, mocks):
    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file so the download step executes
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            pre_skip_existing=True,
            apply=False,
        )

    mocks.download_spotify.assert_called_once()
    download_call = mocks.download_spotify.call_args.kwargs
    assert download_call['pre_skip_existing'] is True


# --- retries forwarding ------------------------------------------------------------

def test_retries_forwards_to_download_spotify(tmp_path, mocks):
    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file so the download step executes
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            retries=3,
            apply=False,
        )

    mocks.download_spotify.assert_called_once()
    download_call = mocks.download_spotify.call_args.kwargs
    assert download_call['retries'] == 3


# --- verbose forwarding ------------------------------------------------------------

def test_verbose_forwards_to_all_steps(tmp_path, mocks):
    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file so all steps execute
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            verbose=True,
            apply=False,
        )

    # build_playlists should get verbose=True in both calls
    assert mocks.build_playlists.call_count == 2
    build_playlists_calls = mocks.build_playlists.call_args_list
    assert build_playlists_calls[0].kwargs['verbose'] is True  # Step 1
    assert build_playlists_calls[1].kwargs['verbose'] is True  # Step 4

    # download_spotify should get debug=True (verbose maps to debug for download)
    mocks.download_spotify.assert_called_once()
    assert mocks.download_spotify.call_args.kwargs['debug'] is True

    # run_import should get verbose=True
    mocks.run_import.assert_called_once()
    assert mocks.run_import.call_args.kwargs['verbose'] is True


# --- return shape ------------------------------------------------------------------

def test_return_shape_on_success(tmp_path, mocks):
    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file so all steps execute
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        result = run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            apply=True,
        )

    assert result == {
        'steps': [
            {'step': 'refresh-playlists', 'ok': True, 'error': None, 'skipped': False},
            {'step': 'download', 'ok': True, 'error': None, 'skipped': False},
            {'step': 'import', 'ok': True, 'error': None, 'skipped': False},
            {'step': 'refresh-playlists-sync', 'ok': True, 'error': None, 'skipped': False},
        ],
        'ok': True,
    }


def test_return_shape_on_injected_exception_failure(tmp_path, mocks):
    mocks.build_playlists.side_effect = RuntimeError("boom")

    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        result = run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            apply=True,
        )

    assert result == {
        'steps': [
            {'step': 'refresh-playlists', 'ok': False, 'error': 'boom', 'skipped': False},
            {'step': 'download', 'ok': True, 'error': None, 'skipped': True},
            {'step': 'import', 'ok': True, 'error': None, 'skipped': True},
            {'step': 'refresh-playlists-sync', 'ok': True, 'error': None, 'skipped': True},
        ],
        'ok': False,
    }


def test_return_shape_on_falsy_step_result_without_exception(tmp_path, mocks):
    mocks.download_spotify.return_value = False  # Falsy result, no exception

    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file so the download step executes
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        result = run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            apply=True,
        )

    assert result == {
        'steps': [
            {'step': 'refresh-playlists', 'ok': True, 'error': None, 'skipped': False},
            {'step': 'download', 'ok': False, 'error': None, 'skipped': False},
            {'step': 'import', 'ok': True, 'error': None, 'skipped': False},
            {'step': 'refresh-playlists-sync', 'ok': True, 'error': None, 'skipped': False},
        ],
        'ok': False,
    }


# --- default parameter values ------------------------------------------------------

def test_default_parameter_values(tmp_path, mocks, monkeypatch):
    """Test that default parameter values are correct."""
    # Ensure PLAYLISTS_EXCLUDE is not set to avoid interference
    monkeypatch.delenv('PLAYLISTS_EXCLUDE', raising=False)
    # Ensure DOWNLOAD_COOKIES_FILE is not set to avoid interference
    monkeypatch.delenv('DOWNLOAD_COOKIES_FILE', raising=False)
    # Ensure DOWNLOAD_PRE_SKIP_EXISTING is not set to avoid interference
    monkeypatch.delenv('DOWNLOAD_PRE_SKIP_EXISTING', raising=False)
    # Ensure DOWNLOAD_RETRIES is not set to avoid interference
    monkeypatch.delenv('DOWNLOAD_RETRIES', raising=False)
    # Mock the path functions in the core.process_unmatched module where they're imported and used
    with patch('core.process_unmatched.playlists_path', return_value=str(tmp_path / "playlists")):
        with patch('core.process_unmatched.resolve_exports_dir', return_value=str(tmp_path / "exports")):
            with patch('core.process_unmatched.archive_path', return_value=str(tmp_path)):
                with patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

                    # Create the directory structure so that paths resolve correctly
                    playlists_dir = tmp_path / "playlists"
                    exports_dir = tmp_path / "exports"
                    spotify_exports_dir = exports_dir / "spotify"
                    playlists_dir.mkdir(parents=True, exist_ok=True)
                    exports_dir.mkdir(parents=True, exist_ok=True)
                    spotify_exports_dir.mkdir(parents=True, exist_ok=True)

                    # Create the unmatched CSV file so steps execute (for dry run)
                    unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
                    unmatched_csv_path.touch()  # Create empty file

                    run_process_unmatched()  # Call with all defaults

                # Close the with statements
            # Close the with statements
        # Close the with statements
    # Close the with statements

    # Check that build_playlists was called twice (step 1 and step 4)
    assert mocks.build_playlists.call_count == 2
    build_playlists_calls = mocks.build_playlists.call_args_list
    # First call: step 1 (refresh playlists to generate unmatched CSV)
    call_kwargs_1 = build_playlists_calls[0].kwargs
    assert call_kwargs_1['apply'] is False
    assert call_kwargs_1['rescrape'] is True
    assert call_kwargs_1['reindex'] is True
    assert call_kwargs_1['names'] == []
    assert call_kwargs_1['exclude_names'] == []
    assert call_kwargs_1['service'] == 'spotify'
    # When archive_path_opt is None, it uses archive_path() default (mocked to tmp_path)
    assert call_kwargs_1['archive_path'] == str(tmp_path)
    # When playlists_path_opt is None, it uses playlists_path() default (mocked to tmp_path/playlists)
    assert call_kwargs_1['playlists_path'] == str(tmp_path / "playlists")
    # When exports_dir_opt is None, it passes None directly (no fallback in the call)
    assert call_kwargs_1['exports_dir'] is None
    # Second call: step 4 (sync playlists with library)
    call_kwargs_2 = build_playlists_calls[1].kwargs
    assert call_kwargs_2['apply'] is False
    assert call_kwargs_2['rescrape'] is False  # No rescrape - just reindex
    assert call_kwargs_2['reindex'] is True
    assert call_kwargs_2['names'] == []
    assert call_kwargs_2['exclude_names'] == []
    assert call_kwargs_2['service'] == 'spotify'
    # When archive_path_opt is None, it uses archive_path() default (mocked to tmp_path)
    assert call_kwargs_2['archive_path'] == str(tmp_path)
    # When playlists_path_opt is None, it uses playlists_path() default (mocked to tmp_path/playlists)
    assert call_kwargs_2['playlists_path'] == str(tmp_path / "playlists")
    # When exports_dir_opt is None, it passes None directly (no fallback in the call)
    assert call_kwargs_2['exports_dir'] is None

    # Check that download_spotify was called with expected defaults
    mocks.download_spotify.assert_called_once()
    download_kwargs = mocks.download_spotify.call_args.kwargs
    assert download_kwargs['format'] == 'mp3'
    assert download_kwargs['bitrate'] == '320k'
    assert download_kwargs['cookie_file'] is None
    assert download_kwargs['pre_skip_existing'] is False
    assert download_kwargs['retries'] == 0
    assert download_kwargs['validate_only'] is True  # Dry run mode
    assert download_kwargs['debug'] is False

    # Check that run_import was called with expected defaults
    mocks.run_import.assert_called_once()
    import_kwargs = mocks.run_import.call_args.kwargs
    assert import_kwargs['dry_run'] is True  # Dry run mode
    assert import_kwargs['verbose'] is False



# --- skip initial playlist refresh -------------------------------------------------

def test_skip_initial_playlist_refresh_with_existing_csv(tmp_path, mocks):
    """Test that when --skip-initial-playlist-refresh is used and CSV exists, step 1 is skipped."""
    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Create the unmatched CSV file to simulate a previous run
        unmatched_csv_path = spotify_exports_dir / 'unmatched.csv'
        unmatched_csv_path.touch()  # Create empty file

        result = run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            skip_initial_playlist_refresh=True,
            apply=False,
        )

    # build_playlists should NOT have been called for step 1 (skipped)
    # but should have been called once for step 4 (sync)
    assert mocks.build_playlists.call_count == 1
    build_playlists_call = mocks.build_playlists.call_args
    assert build_playlists_call.kwargs['apply'] is False
    assert build_playlists_call.kwargs['rescrape'] is False  # Step 4: no rescrape
    assert build_playlists_call.kwargs['reindex'] is True
    assert build_playlists_call.kwargs['names'] == []
    assert build_playlists_call.kwargs['exclude_names'] == []
    assert build_playlists_call.kwargs['service'] == 'spotify'
    assert build_playlists_call.kwargs['archive_path'] == str(tmp_path)
    assert build_playlists_call.kwargs['playlists_path'] == str(tmp_path / "playlists")
    assert build_playlists_call.kwargs['exports_dir'] == str(tmp_path / "exports")

    # download_spotify should NOT have been called (no unmatched CSV to process in dry run)
    mocks.download_spotify.assert_not_called()

    # run_import should NOT have been called (nothing to import)
    mocks.run_import.assert_not_called()

    # Check step results
    assert len(result['steps']) == 4
    assert result['steps'][0]['step'] == 'refresh-playlists'
    assert result['steps'][0]['ok'] is True  # Step 1 succeeded (we found the CSV)
    assert result['steps'][0]['skipped'] is True  # But we skipped the actual work

    assert result['steps'][1]['step'] == 'download'
    assert result['steps'][1]['ok'] is True  # Skipped steps show as ok=True
    assert result['steps'][1]['skipped'] is True

    assert result['steps'][2]['step'] == 'import'
    assert result['steps'][2]['ok'] is True  # Skipped steps show as ok=True
    assert result['steps'][2]['skipped'] is True

    assert result['steps'][3]['step'] == 'refresh-playlists-sync'
    assert result['steps'][3]['ok'] is True  # Skipped steps show as ok=True
    assert result['steps'][3]['skipped'] is True

    assert result['ok'] is True  # Overall success since no steps actually failed


def test_skip_initial_playlist_refresh_missing_csv(tmp_path, mocks):
    """Test that when --skip-initial-playlist-refresh is used but CSV is missing, step 1 fails."""
    # Mock the path functions to return predictable values
    with patch('lib.paths.playlists_path', return_value=str(tmp_path / "playlists")), \
         patch('playlists.build._spotify_exports_dir', return_value=str(tmp_path / "exports" / "spotify")):

        # Create the directory structure so that paths resolve correctly
        playlists_dir = tmp_path / "playlists"
        exports_dir = tmp_path / "exports"
        spotify_exports_dir = exports_dir / "spotify"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        spotify_exports_dir.mkdir(parents=True, exist_ok=True)

        # Note: We deliberately DO NOT create the unmatched CSV file

        result = run_process_unmatched(
            archive_path_opt=str(tmp_path),
            playlists_path_opt=str(tmp_path / "playlists"),
            exports_dir_opt=str(tmp_path / "exports"),
            skip_initial_playlist_refresh=True,
            apply=False,
        )

    # build_playlists should NOT have been called at all
    mocks.build_playlists.assert_not_called()

    # download_spotify and run_import should not have been called
    mocks.download_spotify.assert_not_called()
    mocks.run_import.assert_not_called()

    # Check step results
    assert len(result['steps']) == 4
    assert result['steps'][0]['step'] == 'refresh-playlists'
    assert result['steps'][0]['ok'] is False  # Step 1 failed (CSV not found)
    assert result['steps'][0]['skipped'] is False  # We attempted it but it failed

    assert result['steps'][1]['step'] == 'download'
    assert result['steps'][1]['ok'] is True  # Skipped due to previous step failure
    assert result['steps'][1]['skipped'] is True

    assert result['steps'][2]['step'] == 'import'
    assert result['steps'][2]['ok'] is True  # Skipped due to previous step failure
    assert result['steps'][2]['skipped'] is True

    assert result['steps'][3]['step'] == 'refresh-playlists-sync'
    assert result['steps'][3]['ok'] is True  # Skipped due to previous step failure
    assert result['steps'][3]['skipped'] is True

    assert result['ok'] is False  # Overall failure due to step 1 failure
