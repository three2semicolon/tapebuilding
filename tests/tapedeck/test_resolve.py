"""Tests for tapedeck.resolve - TEST_PLANS.md section 5, tapedeck/resolve.py.

Fixtures build a small crate directory tree by hand - resolve.py never
reads audio content, only paths and directory names, so plain touch files
are enough (no need for tests/lib/conftest.py's real-audio
make_tagged_file fixture here).

Playlist resolution goes through lib.m3u.read_m3u8(), which has its own
real tests elsewhere (tests/lib/test_m3u.py, per README.md). These tests
patch tapedeck.resolve.read_m3u8 directly rather than writing real .m3u8
files, so a change to the on-disk m3u8 format can't silently break this
file - only a change to read_m3u8()'s return shape
({'track_ids', 'existing', 'missing'}) would.
"""
import os

import pytest

from tapedeck.resolve import need_index_for, resolve_targets


# --- fixtures ----------------------------------------------------------------

@pytest.fixture
def crate(tmp_path):
    """A clean album, a folder-basename-ambiguous pair, a nested
    soundtrack dir, and a loose single."""
    root = tmp_path / "crate"

    album = root / "albums" / "Artist - Album"
    album.mkdir(parents=True)
    (album / "01 Track One.mp3").touch()
    (album / "02 Track Two.mp3").touch()

    # two folders that normalize_key() to the same key (dashes/whitespace
    # collapse identically) - exercises the ambiguous-match branch.
    (root / "albums" / "Dup Name").mkdir(parents=True)
    (root / "albums" / "Dup - Name").mkdir(parents=True)

    soundtrack = root / "soundtracks" / "Sonic" / "Sonic Unleashed"
    soundtrack.mkdir(parents=True)
    (soundtrack / "01 Theme.mp3").touch()

    singles = root / "singles"
    singles.mkdir(parents=True)
    (singles / "Loose Song.mp3").touch()

    return root


class _FakeMatchIndex:
    """Stand-in for lib.catalog.matcher.MatchIndex - only the one method
    _resolve_song() actually calls."""

    def __init__(self, candidates):
        self._candidates = candidates

    def candidates_exact(self, norm_title):
        return self._candidates


# --- need_index_for ------------------------------------------------------------

def test_need_index_for_soundtrack_and_playlist_always_false(crate):
    assert need_index_for('soundtrack', ['anything'], str(crate)) is False
    assert need_index_for('playlist', ['anything'], str(crate)) is False


def test_need_index_for_path_form_specs_are_false(crate):
    assert need_index_for('album', [os.path.join('albums', 'Artist - Album')], str(crate)) is False
    assert need_index_for('song', [os.path.join('singles', 'Loose Song.mp3')], str(crate)) is False


def test_need_index_for_false_for_album_by_folder_basename(crate):
    assert need_index_for('album', ['Artist - Album'], str(crate)) is False


def test_need_index_for_true_for_album_by_name():
    """An album spec that matches neither a path nor a folder basename
    needs the tag-fallback index."""
    assert need_index_for('album', ['Some Totally Different Album'], '/nonexistent-crate') is True


def test_need_index_for_true_for_song_by_name(crate):
    assert need_index_for('song', ['Loose Song'], str(crate)) is True


def test_need_index_for_false_for_song_by_path(crate):
    assert need_index_for('song', [os.path.join('singles', 'Loose Song.mp3')], str(crate)) is False


# --- resolve_targets: album ------------------------------------------------------

def test_resolve_album_by_path(crate):
    spec = os.path.join('albums', 'Artist - Album')
    res = resolve_targets('album', [spec], str(crate))
    assert res['folders'] == [os.path.join(str(crate), spec)]
    assert res['files'] == []
    assert res['m3u8'] == []
    assert res['warnings'] == []


def test_resolve_album_by_folder_basename(crate):
    res = resolve_targets('album', ['Artist - Album'], str(crate))
    assert res['folders'] == [str(crate / 'albums' / 'Artist - Album')]
    assert res['warnings'] == []


def test_resolve_album_ambiguous_folder_basename_warns_and_loads_all(crate):
    res = resolve_targets('album', ['Dup Name'], str(crate))
    assert set(res['folders']) == {
        str(crate / 'albums' / 'Dup Name'),
        str(crate / 'albums' / 'Dup - Name'),
    }
    assert len(res['warnings']) == 1
    assert "matched 2 folders" in res['warnings'][0]


def test_resolve_album_tag_fallback_via_index(crate):
    """Folder name diverges from the album tag - falls back to matching
    an index entry's 'album' field."""
    track_path = str(crate / 'albums' / 'Artist - Album' / '01 Track One.mp3')
    index = [{'album': 'Renamed Album', 'path': track_path}]
    res = resolve_targets('album', ['Renamed Album'], str(crate), index=index)
    assert res['folders'] == [str(crate / 'albums' / 'Artist - Album')]
    assert res['warnings'] == []


def test_resolve_album_no_match_no_index_warns(crate):
    res = resolve_targets('album', ['Nonexistent Album'], str(crate))
    assert res['folders'] == []
    assert len(res['warnings']) == 1
    assert "no folder match and no index built" in res['warnings'][0]


def test_resolve_album_no_match_with_index_warns(crate):
    res = resolve_targets('album', ['Nonexistent Album'], str(crate), index=[])
    assert res['folders'] == []
    assert "no match (folder basename or album tag)" in res['warnings'][0]


# --- resolve_targets: song --------------------------------------------------------

def test_resolve_song_by_path(crate):
    spec = os.path.join('singles', 'Loose Song.mp3')
    res = resolve_targets('song', [spec], str(crate))
    assert res['files'] == [os.path.join(str(crate), spec)]
    assert res['warnings'] == []


def test_resolve_song_by_name_via_index(crate):
    hit_path = str(crate / 'singles' / 'Loose Song.mp3')
    mindex = _FakeMatchIndex([{'e': {'path': hit_path}, 'artists': {'someartist'}}])
    res = resolve_targets('song', ['Loose Song'], str(crate), index=[{}], mindex=mindex)
    assert res['files'] == [hit_path]
    assert res['warnings'] == []


def test_resolve_song_by_name_no_index_warns(crate):
    res = resolve_targets('song', ['Loose Song'], str(crate))
    assert res['files'] == []
    assert "pass a crate file path, or run with --reindex" in res['warnings'][0]


def test_resolve_song_by_name_no_title_match_warns(crate):
    mindex = _FakeMatchIndex([])
    res = resolve_targets('song', ['Nonexistent Track'], str(crate), index=[{}], mindex=mindex)
    assert res['files'] == []
    assert "no title match in the index" in res['warnings'][0]


def test_resolve_song_multiple_matches_loads_all_and_warns(crate):
    a = str(crate / 'singles' / 'Loose Song.mp3')
    b = str(crate / 'albums' / 'Artist - Album' / '01 Track One.mp3')
    mindex = _FakeMatchIndex([
        {'e': {'path': a}, 'artists': {'x'}},
        {'e': {'path': b}, 'artists': {'x'}},
    ])
    res = resolve_targets('song', ['Some Title'], str(crate), index=[{}], mindex=mindex)
    assert set(res['files']) == {a, b}
    assert "matched 2 files" in res['warnings'][0]


def test_resolve_song_artist_part_narrows_candidates(crate):
    """'Artist - Title' form should filter candidates by artist overlap,
    not just title."""
    keep = str(crate / 'singles' / 'Loose Song.mp3')
    drop = str(crate / 'albums' / 'Artist - Album' / '01 Track One.mp3')
    mindex = _FakeMatchIndex([
        {'e': {'path': keep}, 'artists': {'rightartist'}},
        {'e': {'path': drop}, 'artists': {'wrongartist'}},
    ])
    res = resolve_targets('song', ['RightArtist - Some Title'], str(crate), index=[{}], mindex=mindex)
    assert res['files'] == [keep]


# --- resolve_targets: soundtrack --------------------------------------------------

def test_resolve_soundtrack_by_path(crate):
    spec = os.path.join('soundtracks', 'Sonic', 'Sonic Unleashed')
    res = resolve_targets('soundtrack', [spec], str(crate))
    assert res['folders'] == [os.path.join(str(crate), spec)]
    assert res['warnings'] == []


def test_resolve_soundtrack_by_name(crate):
    res = resolve_targets('soundtrack', ['Sonic Unleashed'], str(crate))
    assert res['folders'] == [str(crate / 'soundtracks' / 'Sonic' / 'Sonic Unleashed')]
    assert res['warnings'] == []


def test_resolve_soundtrack_no_match_warns(crate):
    res = resolve_targets('soundtrack', ['Nonexistent'], str(crate))
    assert res['folders'] == []
    assert "no dir match under soundtracks/" in res['warnings'][0]


# --- resolve_targets: playlist -----------------------------------------------------

def test_resolve_playlist_no_playlists_path_warns(crate):
    res = resolve_targets('playlist', ['__mom'], str(crate), playlists_path=None)
    assert res['m3u8'] == []
    assert "PLAYLISTS_PATH not set" in res['warnings'][0]


def test_resolve_playlist_by_name(crate, tmp_path, monkeypatch):
    playlists_dir = tmp_path / "playlists_src"
    playlists_dir.mkdir()
    m3u_path = playlists_dir / "__mom.m3u8"
    m3u_path.touch()
    existing_track = str(crate / 'albums' / 'Artist - Album' / '01 Track One.mp3')

    monkeypatch.setattr("tapedeck.resolve.read_m3u8", lambda path: {
        'track_ids': ['abc123'], 'existing': [existing_track], 'missing': []
    })

    res = resolve_targets('playlist', ['__mom'], str(crate), playlists_path=str(playlists_dir))
    assert res['m3u8'] == [str(m3u_path)]
    assert res['files'] == [existing_track]
    assert res['warnings'] == []


def test_resolve_playlist_by_filename_under_playlists_path(crate, tmp_path, monkeypatch):
    """Spec given as a bare .m3u8 filename resolves as a path form,
    skipping the name-search branch entirely."""
    playlists_dir = tmp_path / "playlists_src"
    playlists_dir.mkdir()
    m3u_path = playlists_dir / "__mom.m3u8"
    m3u_path.touch()

    monkeypatch.setattr("tapedeck.resolve.read_m3u8", lambda path: {
        'track_ids': [], 'existing': [], 'missing': []
    })

    res = resolve_targets('playlist', ['__mom.m3u8'], str(crate), playlists_path=str(playlists_dir))
    assert res['m3u8'] == [str(m3u_path)]
    assert res['warnings'] == []


def test_resolve_playlist_missing_tracks_warns(crate, tmp_path, monkeypatch):
    playlists_dir = tmp_path / "playlists_src"
    playlists_dir.mkdir()
    (playlists_dir / "__mom.m3u8").touch()

    monkeypatch.setattr("tapedeck.resolve.read_m3u8", lambda path: {
        'track_ids': [], 'existing': [], 'missing': ['Ghost Track - Missing Artist']
    })

    res = resolve_targets('playlist', ['__mom'], str(crate), playlists_path=str(playlists_dir))
    assert res['files'] == []
    assert len(res['warnings']) == 1
    assert "1 track(s) not in crate (skipped): Ghost Track - Missing Artist" in res['warnings'][0]


def test_resolve_playlist_ambiguous_name_loads_all(crate, tmp_path, monkeypatch):
    playlists_dir = tmp_path / "playlists_src"
    playlists_dir.mkdir()
    (playlists_dir / "__mom.m3u8").touch()
    (playlists_dir / "__mom.m3u").touch()

    monkeypatch.setattr("tapedeck.resolve.read_m3u8", lambda path: {
        'track_ids': [], 'existing': [], 'missing': []
    })

    res = resolve_targets('playlist', ['__mom'], str(crate), playlists_path=str(playlists_dir))
    assert len(res['m3u8']) == 2
    assert any("matched 2 files" in w for w in res['warnings'])


def test_resolve_playlist_no_match_warns(crate, tmp_path):
    playlists_dir = tmp_path / "playlists_src"
    playlists_dir.mkdir()
    res = resolve_targets('playlist', ['nonexistent'], str(crate), playlists_path=str(playlists_dir))
    assert res['m3u8'] == []
    assert "no .m3u8 match in" in res['warnings'][0]
