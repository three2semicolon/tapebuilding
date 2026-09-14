"""Tests for tapedeck.copy - TEST_PLANS.md 'tapedeck/copy.py' section.

Plain touch/write files are enough here - stage()/unstage() only care
about paths and byte content, never audio tags. Playlist-refcount tests
patch tapedeck.copy.read_m3u8 directly, standing in for the .m3u8 file
that would actually be staged under tapedeck/playlists/ - lib.m3u itself
has its own real tests elsewhere (tests/lib/test_m3u.py).
"""
import os

from tapedeck.copy import stage, unstage


# --- stage() -----------------------------------------------------------------

def test_stage_copies_by_default(tmp_path):
    crate = tmp_path / "crate"
    deck = tmp_path / "deck"
    src_dir = crate / "albums" / "Artist - Album"
    src_dir.mkdir(parents=True)
    src_file = src_dir / "01 Track.mp3"
    src_file.write_text("audio-bytes")

    items = {'folders': [str(src_dir)], 'files': [], 'm3u8': []}
    summary = stage(items, str(crate), str(deck))

    dst = deck / "albums" / "Artist - Album" / "01 Track.mp3"
    assert dst.read_text() == "audio-bytes"
    assert summary == {'copied': 1, 'linked': 0, 'skipped': 0, 'overwritten': 0, 'errors': 0}
    # a real copy, not a hardlink
    assert os.stat(src_file).st_ino != os.stat(dst).st_ino


def test_stage_hardlinks_with_link_flag_same_volume_only(tmp_path):
    crate = tmp_path / "crate"
    deck = tmp_path / "deck"
    src_dir = crate / "singles"
    src_dir.mkdir(parents=True)
    src_file = src_dir / "Song.mp3"
    src_file.write_text("audio-bytes")

    items = {'folders': [], 'files': [str(src_file)], 'm3u8': []}
    summary = stage(items, str(crate), str(deck), mode='link')

    dst = deck / "singles" / "Song.mp3"
    assert os.stat(src_file).st_ino == os.stat(dst).st_ino
    assert summary == {'copied': 0, 'linked': 1, 'skipped': 0, 'overwritten': 0, 'errors': 0}


def test_stage_skips_existing_unless_overwrite(tmp_path):
    crate = tmp_path / "crate"
    deck = tmp_path / "deck"
    src_dir = crate / "singles"
    src_dir.mkdir(parents=True)
    src_file = src_dir / "Song.mp3"
    src_file.write_text("new-bytes")

    dst_file = deck / "singles" / "Song.mp3"
    dst_file.parent.mkdir(parents=True)
    dst_file.write_text("old-bytes")

    items = {'folders': [], 'files': [str(src_file)], 'm3u8': []}

    summary = stage(items, str(crate), str(deck))
    assert dst_file.read_text() == "old-bytes"
    assert summary['skipped'] == 1
    assert summary['overwritten'] == 0

    summary2 = stage(items, str(crate), str(deck), overwrite=True)
    assert dst_file.read_text() == "new-bytes"
    assert summary2['overwritten'] == 1


# --- unstage() -----------------------------------------------------------------

def test_unstage_removes_files(tmp_path):
    crate = tmp_path / "crate"
    deck = tmp_path / "deck"
    src_dir = crate / "albums" / "Artist - Album"
    src_dir.mkdir(parents=True)
    src_file = src_dir / "01.mp3"
    src_file.write_text("x")

    items = {'folders': [str(src_dir)], 'files': [], 'm3u8': []}
    stage(items, str(crate), str(deck))
    dst_file = deck / "albums" / "Artist - Album" / "01.mp3"
    assert dst_file.exists()

    summary = unstage(items, str(crate), str(deck), kind='album')
    assert summary['removed'] == 1
    assert not dst_file.exists()


def test_unstage_prunes_empty_parent_directories(tmp_path):
    crate = tmp_path / "crate"
    deck = tmp_path / "deck"
    nested = crate / "albums" / "Artist - Album" / "Disc 1"
    nested.mkdir(parents=True)
    (nested / "01.mp3").write_text("x")

    items = {'folders': [str(crate / "albums" / "Artist - Album")], 'files': [], 'm3u8': []}
    stage(items, str(crate), str(deck))
    dst_nested = deck / "albums" / "Artist - Album" / "Disc 1"
    assert dst_nested.exists()

    unstage(items, str(crate), str(deck), kind='album')
    assert not dst_nested.exists()
    # Pinned current behavior, not necessarily ideal: os.walk(topdown=False)
    # snapshots each dir's children before recursing, so a parent that only
    # becomes empty *as a result of* this same pruning pass (its one child
    # just got rmdir'd) isn't re-checked and survives this call - "Disc 1"
    # goes, but "Artist - Album" (now empty) doesn't, until a later
    # unload's pruning pass gets to it.
    assert (deck / "albums" / "Artist - Album").exists()
    assert not any((deck / "albums" / "Artist - Album").iterdir())

    # a subsequent unload's prune pass (a no-op unload here, since nothing
    # is left to remove) finishes the job.
    unstage(items, str(crate), str(deck), kind='album')
    assert not (deck / "albums" / "Artist - Album").exists()
    assert (deck / "albums").exists()  # the subtree root itself is never pruned


def test_unstage_refcounted_shared_track_survives_first_unload(tmp_path, monkeypatch):
    """Load two playlists sharing a track; unload one - the shared track
    should NOT be removed. Unload the second - now it should be."""
    crate = tmp_path / "crate"
    deck = tmp_path / "deck"
    audio_dir = crate / "albums" / "Artist - Album"
    audio_dir.mkdir(parents=True)
    shared_track = audio_dir / "01 Shared.mp3"
    shared_track.write_text("x")

    m3u_a_src = crate / "playlists" / "Playlist A.m3u8"
    m3u_b_src = crate / "playlists" / "Playlist B.m3u8"
    m3u_a_src.parent.mkdir(parents=True, exist_ok=True)
    m3u_a_src.write_text("")  # content is irrelevant - read_m3u8 is mocked below
    m3u_b_src.write_text("")

    items_a = {'folders': [], 'files': [str(shared_track)], 'm3u8': [str(m3u_a_src)]}
    items_b = {'folders': [], 'files': [str(shared_track)], 'm3u8': [str(m3u_b_src)]}

    stage(items_a, str(crate), str(deck))
    stage(items_b, str(crate), str(deck))

    dst_track = deck / "albums" / "Artist - Album" / "01 Shared.mp3"
    dst_m3u_a = deck / "playlists" / "Playlist A.m3u8"
    dst_m3u_b = deck / "playlists" / "Playlist B.m3u8"
    assert dst_track.exists() and dst_m3u_a.exists() and dst_m3u_b.exists()

    # The refcount check reads whichever *other* m3u8 is still staged
    # under tapedeck/playlists/ - since the deck mirrors the crate 1:1,
    # its "existing" references resolve to paths under the tapedeck root
    # (the staged copy), not the crate.
    monkeypatch.setattr("tapedeck.copy.read_m3u8", lambda path: {
        'track_ids': [], 'existing': [str(dst_track)], 'missing': []
    })

    summary1 = unstage(items_a, str(crate), str(deck), kind='playlist')
    assert summary1['protected'] == 1
    assert dst_track.exists()       # shared track survives
    assert not dst_m3u_a.exists()   # its own m3u8 is still removed
    assert dst_m3u_b.exists()

    summary2 = unstage(items_b, str(crate), str(deck), kind='playlist')
    assert summary2['removed'] == 1
    assert summary2['protected'] == 0
    assert not dst_track.exists()   # now actually removed
    assert not dst_m3u_b.exists()


def test_unstage_playlist_refcount_does_not_protect_independently_loaded_track(tmp_path):
    """Documented sharp edge: a track independently loaded via
    `load album`/`load song` is not protected by playlist refcounting
    when it's unloaded via that same album/song kind - refcounting is
    scoped to kind == 'playlist' unloads only."""
    crate = tmp_path / "crate"
    deck = tmp_path / "deck"
    audio_dir = crate / "albums" / "Artist - Album"
    audio_dir.mkdir(parents=True)
    track = audio_dir / "01 Track.mp3"
    track.write_text("x")

    album_items = {'folders': [str(audio_dir)], 'files': [], 'm3u8': []}
    stage(album_items, str(crate), str(deck))
    dst_track = deck / "albums" / "Artist - Album" / "01 Track.mp3"
    assert dst_track.exists()

    # unloading it as an *album* (not a playlist) must not consult - or be
    # protected by - any playlist's refcount, even if one exists that
    # references this same track.
    summary = unstage(album_items, str(crate), str(deck), kind='album')
    assert summary['removed'] == 1
    assert summary['protected'] == 0
    assert not dst_track.exists()
