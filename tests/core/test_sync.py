"""Tests for core.sync - TEST_PLANS.md 'core/sync.py' section.

sync.py is documented as a thin promotion of the README's
`playlists --apply --rescrape` flow to a function - no logic of its own,
just a forwarding call into playlists.build.build_playlists(). These
tests check the forwarding, not build_playlists()'s own behavior (that
has its own real tests in tests/playlists/test_build.py).
"""
from unittest.mock import MagicMock

import pytest

import core.sync as sync_mod
from core.sync import run_sync


@pytest.fixture
def build_playlists_mock(monkeypatch):
    mock = MagicMock(return_value="build-playlists-result")
    monkeypatch.setattr(sync_mod, "build_playlists", mock)
    return mock


def test_run_sync_forwards_to_build_playlists_with_apply_and_rescrape_true(build_playlists_mock):
    result = run_sync(
        names=['My Playlist'], covers=True, verbose=True,
        playlists_path='/playlists', archive_path='/crate', exports_dir='/exports',
    )

    build_playlists_mock.assert_called_once_with(
        apply=True,
        rescrape=True,
        names=['My Playlist'],
        covers=True,
        verbose=True,
        playlists_path='/playlists',
        archive_path='/crate',
        exports_dir='/exports',
    )
    # pure passthrough - whatever build_playlists() returns is what run_sync() returns
    assert result == "build-playlists-result"


def test_names_defaults_to_empty_list_not_none(build_playlists_mock):
    run_sync()
    assert build_playlists_mock.call_args.kwargs['names'] == []


def test_covers_flag_forwards_to_build_playlists(build_playlists_mock):
    run_sync(covers=True)
    assert build_playlists_mock.call_args.kwargs['covers'] is True

    run_sync(covers=False)
    assert build_playlists_mock.call_args.kwargs['covers'] is False


def test_names_param_scopes_to_specific_playlists(build_playlists_mock):
    run_sync(names=['Road Trip', 'spotify:playlist:xyz'])
    assert build_playlists_mock.call_args.kwargs['names'] == ['Road Trip', 'spotify:playlist:xyz']


def test_no_dry_run_mode_of_its_own():
    """run_sync() has no apply/dry-run parameter at all - previewing is
    documented as calling build_playlists(apply=False, ...) directly
    instead. Pin the absence of the parameter (a caller can't accidentally
    get a "preview" out of run_sync() itself)."""
    import inspect
    assert 'apply' not in inspect.signature(run_sync).parameters
    with pytest.raises(TypeError):
        run_sync(apply=False)


def test_documented_preview_path_uses_the_same_build_playlists_function():
    """The module docstring's claim that calling
    playlists.build.build_playlists(apply=False, ...) directly is an
    equivalent preview only holds if sync.py hasn't wrapped or shadowed
    that function with something that behaves differently - assert it's
    literally the same function object, not a re-implementation."""
    from playlists.build import build_playlists as build_playlists_real
    assert sync_mod.build_playlists is build_playlists_real
