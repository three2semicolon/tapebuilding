"""Tests for tapedeck.deck - TEST_PLANS.md 'tapedeck/deck.py' section.

load_tapedeck()/unload_tapedeck() are tested here by mocking their
collaborators (resolve_targets, stage/unstage, get_index/MatchIndex,
lib.paths' resolvers) rather than building a real crate - resolve.py and
copy.py already have their own real, direct tests. What matters here is
deck.py's own wiring: does it call the right things, in the right order,
without needing a `reindex` kwarg it doesn't have.
"""
from unittest.mock import MagicMock

import pytest

import tapedeck.deck as deck_mod
from tapedeck.deck import _fmt_size, _maybe_index, playlists_root, unload_tapedeck


# --- _fmt_size -----------------------------------------------------------------

@pytest.mark.parametrize("n,expected", [
    (0, "0 B"),
    (512, "512 B"),
    (1024, "1.0 KB"),
    (1536, "1.5 KB"),
    (1024 * 1024, "1.0 MB"),
    (1024 ** 3, "1.0 GB"),
])
def test_fmt_size_human_readable(n, expected):
    assert _fmt_size(n) == expected


# --- _maybe_index ----------------------------------------------------------------

def test_maybe_index_only_builds_when_need_index_for_says_to(monkeypatch):
    fake_index = ["entry"]
    fake_mindex = MagicMock()
    get_index_mock = MagicMock(return_value=fake_index)
    match_index_mock = MagicMock(return_value=fake_mindex)
    monkeypatch.setattr(deck_mod, "get_index", get_index_mock)
    monkeypatch.setattr(deck_mod, "MatchIndex", match_index_mock)
    monkeypatch.setattr(deck_mod, "resolve_exports_dir", MagicMock(return_value="/fake/exports"))

    # need_index_for says no -> skip the index build entirely
    monkeypatch.setattr(deck_mod, "need_index_for", lambda kind, specs, crate: False)
    index, mindex = _maybe_index('album', ['Some Album'], '/crate')
    assert (index, mindex) == (None, None)
    get_index_mock.assert_not_called()
    match_index_mock.assert_not_called()

    # need_index_for says yes -> build it
    monkeypatch.setattr(deck_mod, "need_index_for", lambda kind, specs, crate: True)
    index, mindex = _maybe_index('album', ['Some Album'], '/crate')
    assert index is fake_index
    assert mindex is fake_mindex
    get_index_mock.assert_called_once()
    match_index_mock.assert_called_once_with(fake_index)


# --- unload_tapedeck --------------------------------------------------------------

def test_unload_tapedeck_does_not_raise_attributeerror_on_reindex_kwarg(monkeypatch, tmp_path):
    """Regression test for a documented pre-refactor bug: unload_tapedeck()
    used to unconditionally read a possibly-undefined `reindex` arg."""
    crate = tmp_path / "crate"
    deck = tmp_path / "deck"

    monkeypatch.setattr(deck_mod, "crate_root", lambda cli=None: str(crate))
    monkeypatch.setattr(deck_mod, "tapedeck_root", lambda cli=None: str(deck))
    monkeypatch.setattr(deck_mod, "_resolve_playlists_path", lambda cli=None: str(tmp_path / "playlists"))
    monkeypatch.setattr(deck_mod, "need_index_for", lambda kind, specs, crate: False)
    monkeypatch.setattr(deck_mod, "resolve_targets", lambda *a, **k: {
        'folders': [], 'files': ['/crate/albums/Artist - Album/01.mp3'], 'm3u8': [], 'warnings': []
    })
    unstage_mock = MagicMock(return_value={
        'removed': 0, 'protected': 0, 'missing': 0, 'errors': 0, 'm3u8_removed': 0
    })
    monkeypatch.setattr(deck_mod, "unstage", unstage_mock)

    # the call itself is the regression test: no AttributeError/TypeError
    # from a missing `reindex` kwarg anywhere on this path.
    unload_tapedeck('album', ['Some Album'], apply=True)
    unstage_mock.assert_called_once()


# --- playlists_root ----------------------------------------------------------------

def test_playlists_root_returns_none_gracefully_when_playlists_path_unset(monkeypatch):
    """load/unload of album/song/soundtrack shouldn't require
    PLAYLISTS_PATH to be set at all."""
    def raise_value_error(cli=None):
        raise ValueError("PLAYLISTS_PATH not set")
    monkeypatch.setattr(deck_mod, "_resolve_playlists_path", raise_value_error)
    assert playlists_root() is None


def test_playlists_root_returns_path_when_set(monkeypatch):
    monkeypatch.setattr(deck_mod, "_resolve_playlists_path", lambda cli=None: "/some/playlists")
    assert playlists_root() == "/some/playlists"
