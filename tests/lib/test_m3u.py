"""Tests for lib.m3u - TEST_PLANS.md 'lib/m3u.py' section.

Written against the actual current source. write_m3u8()/read_m3u8() are
tested against real files on disk (not mocked) since the atomicity and
relative-path behavior only mean something when actual filesystem
operations happen.
"""
import os

import pytest

from lib.m3u import write_m3u8, read_m3u8, safe_name, render


def _entry(track_id, artist, title, length, path):
    return {"track_id": track_id, "artist": artist, "title": title, "length": length, "path": path}


class TestWriteM3u8:
    def test_is_atomic_no_partial_file_on_failure(self, tmp_path, monkeypatch):
        m3u_path = str(tmp_path / "playlist.m3u8")
        entries = [_entry("t1", "Artist", "Title", 180, str(tmp_path / "Artist" / "Title.mp3"))]

        def boom(*a, **k):
            raise OSError("simulated failure during rename")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            write_m3u8(m3u_path, entries)

        # the atomic rename never completed, so the real destination must
        # not exist - only the tmp file (written first) should be on disk
        assert not os.path.exists(m3u_path)
        assert os.path.exists(m3u_path + ".tmp")

    def test_writes_relative_paths(self, tmp_path):
        m3u_dir = tmp_path / "playlists"
        m3u_dir.mkdir()
        m3u_path = str(m3u_dir / "playlist.m3u8")
        track_path = tmp_path / "crate" / "Artist" / "Song.mp3"
        entries = [_entry("t1", "Artist", "Song", 200, str(track_path))]

        write_m3u8(m3u_path, entries)
        text = open(m3u_path, encoding="utf-8").read()
        assert "../crate/Artist/Song.mp3" in text
        assert str(tmp_path) not in text  # no absolute path leaked in

    def test_includes_spotify_comment_and_extinf(self, tmp_path):
        m3u_path = str(tmp_path / "playlist.m3u8")
        entries = [_entry("abc123", "Artist", "Title", 125, str(tmp_path / "Title.mp3"))]
        write_m3u8(m3u_path, entries)

        lines = open(m3u_path, encoding="utf-8").read().splitlines()
        assert lines[0] == "#EXTM3U"
        assert "#SPOTIFY:abc123" in lines
        assert "#EXTINF:125,Artist - Title" in lines


class TestReadM3u8:
    def test_round_trips_with_write_m3u8(self, tmp_path):
        m3u_path = str(tmp_path / "playlist.m3u8")
        track_path = tmp_path / "Song.mp3"
        track_path.write_bytes(b"")
        entries = [_entry("t1", "Artist", "Song", 180, str(track_path))]
        write_m3u8(m3u_path, entries)

        result = read_m3u8(m3u_path)
        assert result["track_ids"] == ["t1"]
        assert result["existing"] == [os.path.normpath(str(track_path))]
        assert result["missing"] == []

    def test_splits_existing_and_missing_paths(self, tmp_path):
        m3u_path = tmp_path / "playlist.m3u8"
        existing_track = tmp_path / "Real Song.mp3"
        existing_track.write_bytes(b"")
        m3u_path.write_text(
            "#EXTM3U\n"
            "#SPOTIFY:id1\n"
            "#EXTINF:180,Artist - Real Song\n"
            "Real Song.mp3\n"
            "#SPOTIFY:id2\n"
            "#EXTINF:200,Artist - Missing Song\n"
            "Missing Song.mp3\n",
            encoding="utf-8",
        )

        result = read_m3u8(str(m3u_path))
        assert result["track_ids"] == ["id1", "id2"]
        assert result["existing"] == [os.path.normpath(str(existing_track))]
        assert result["missing"] == ["Missing Song.mp3"]

    def test_missing_file_returns_empty_result(self, tmp_path):
        result = read_m3u8(str(tmp_path / "does_not_exist.m3u8"))
        assert result == {"track_ids": [], "existing": [], "missing": []}


class TestSafeName:
    def test_strips_illegal_windows_characters(self):
        assert safe_name("Mix: Set/List") == "Mix SetList"

    def test_transliterates_non_ascii(self):
        assert safe_name("Café") == "Cafe"

    def test_empty_or_none_returns_underscore(self):
        assert safe_name("") == "_"
        assert safe_name(None) == "_"

    def test_strips_trailing_dots_and_whitespace(self):
        assert safe_name("Playlist Name...  ") == "Playlist Name"


class TestRender:
    def test_falls_back_to_title_only_or_artist_only_label(self):
        m3u_path = "/fake/playlist.m3u8"
        text_title_only = render([_entry("t1", "", "Title Only", 100, "/fake/Song.mp3")], m3u_path)
        assert "#EXTINF:100,Title Only" in text_title_only

        text_artist_only = render([_entry("t2", "Artist Only", "", 100, "/fake/Song2.mp3")], m3u_path)
        assert "#EXTINF:100,Artist Only" in text_artist_only

    def test_uses_negative_one_for_unknown_length(self):
        text = render([_entry("t1", "A", "T", 0, "/fake/Song.mp3")], "/fake/playlist.m3u8")
        assert "#EXTINF:-1,A - T" in text
