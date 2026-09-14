"""Tests for lib.tags - TEST_PLANS.md 'lib/tags.py' section.

Written against the actual current source. read_tags()/write_tag()/
scan_audio() tests use the make_tagged_file fixture (tests/lib/conftest.py)
to build real, short, tagged audio files via ffmpeg + mediafile rather than
mocking the tag reader - read_tags() is a thin MediaFile wrapper, so the
only way to actually catch a real regression is to read a real file.

canonical_albumartist()/dominant_album() operate on plain dicts (the shape
read_tags()/scan_audio() produce), so those are tested with hand-built
dicts directly - no audio fixture needed, and it keeps the majority-vote
math easy to follow.
"""
import os

from lib.tags import (
    sanitize,
    primary_token,
    read_tags,
    write_tag,
    canonical_albumartist,
    dominant_album,
    scan_audio,
    safe_move,
)
from lib.text import primary_artist


class TestReadTags:
    def test_returns_expected_dict_shape(self, make_tagged_file):
        path = make_tagged_file(
            artist="Artist A",
            albumartist="Album Artist A",
            album="Album A",
            title="Title A",
            track=3,
        )
        result = read_tags(path)
        assert set(result.keys()) == {
            "path", "artist", "albumartist", "album", "title", "track", "length",
        }
        assert result["path"] == path
        assert result["artist"] == "Artist A"
        assert result["albumartist"] == "Album Artist A"
        assert result["album"] == "Album A"
        assert result["title"] == "Title A"
        assert result["track"] == 3
        assert result["length"] > 0

    def test_returns_none_on_unreadable_file(self, tmp_path):
        bad = tmp_path / "not_actually_audio.mp3"
        bad.write_text("this is not an audio file")
        assert read_tags(str(bad)) is None


class TestWriteTag:
    def test_updates_field_when_value_changes(self, make_tagged_file):
        path = make_tagged_file(title="Old Title")
        write_tag(path, title="New Title")
        assert read_tags(path)["title"] == "New Title"

    def test_skips_save_when_value_unchanged(self, make_tagged_file):
        path = make_tagged_file(albumartist="Same Artist")
        before_mtime = os.path.getmtime(path)
        # differs only in case - normalize_key() should treat this as
        # "unchanged" and skip the save entirely
        write_tag(path, albumartist="same artist")
        after_mtime = os.path.getmtime(path)
        assert after_mtime == before_mtime


class TestSanitize:
    def test_strips_filesystem_unsafe_characters(self):
        assert sanitize('A/B:C*D?E"F<G>H|I') == "ABCDEFGHI"

    def test_strips_trailing_dots_and_whitespace(self):
        assert sanitize("  Track Name...  ") == "Track Name"

    def test_empty_or_none_returns_underscore(self):
        assert sanitize("") == "_"
        assert sanitize(None) == "_"

    def test_all_illegal_characters_returns_underscore(self):
        assert sanitize("///") == "_"


class TestPrimaryToken:
    def test_differs_from_lib_text_primary_artist(self):
        """primary_token() only splits on & or / - deliberately narrower
        than lib.text.primary_artist(), which also splits on comma/feat/
        x/vs. Pin the intentional divergence per PACKAGE_OVERVIEW.md's
        lib/tags.py section - don't 'fix' this into sameness later."""
        assert primary_token("A, B & C") == "A, B"      # comma is NOT a split point here
        assert primary_artist("A, B & C") == "A"          # ...but it is for lib.text
        assert primary_token("A & B") == "A"
        assert primary_token("A / B") == "A"
        assert primary_token("A feat. B") == "A feat. B"  # feat isn't a split point either

    def test_no_separator_returns_whole_string_stripped(self):
        assert primary_token("  Solo Artist  ") == "Solo Artist"

    def test_empty_or_none(self):
        assert primary_token("") == ""
        assert primary_token(None) == ""


class TestCanonicalAlbumartist:
    def test_majority_vote_on_raw_albumartist_string(self):
        files = [
            {"albumartist": "The Band", "artist": ""},
            {"albumartist": "The Band", "artist": ""},
            {"albumartist": "", "artist": "Someone Else"},
        ]
        assert canonical_albumartist(files) == "The Band"

    def test_falls_back_to_dominant_primary_collaborator(self):
        # no single raw credit string reaches 50%, but they all share the
        # same primary_token() collaborator
        files = [
            {"albumartist": "", "artist": "Artist A & Guest 1"},
            {"albumartist": "", "artist": "Artist A & Guest 2"},
            {"albumartist": "", "artist": "Artist A & Guest 3"},
        ]
        assert canonical_albumartist(files) == "Artist A"

    def test_falls_back_to_various_artists_when_nothing_dominates(self):
        files = [
            {"albumartist": "", "artist": "Artist A"},
            {"albumartist": "", "artist": "Artist B"},
            {"albumartist": "", "artist": "Artist C"},
        ]
        assert canonical_albumartist(files) == "Various Artists"

    def test_empty_file_list_returns_various_artists(self):
        assert canonical_albumartist([]) == "Various Artists"


class TestDominantAlbum:
    def test_majority_album_string(self):
        files = [
            {"album": "Album X"},
            {"album": "Album X"},
            {"album": "Different Album"},
        ]
        assert dominant_album(files) == "Album X"

    def test_empty_file_list_returns_empty_string(self):
        assert dominant_album([]) == ""

    def test_ignores_blank_album_field(self):
        files = [{"album": ""}, {"album": "Real Album"}]
        assert dominant_album(files) == "Real Album"


class TestScanAudio:
    def test_recurses_default_subdirs_and_filters_extensions(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="albums/Album A/01 Track.mp3", title="Track One")
        make_tagged_file(filename="singles/Loose Song.mp3", title="Loose Song")
        (tmp_path / "albums" / "Album A" / "cover.jpg").write_bytes(b"not audio")
        # not under albums/ or singles/ - default subdirs shouldn't reach it
        make_tagged_file(filename="other/Ignored.mp3", title="Ignored")

        files = scan_audio(str(tmp_path))
        titles = {f["title"] for f in files}
        assert titles == {"Track One", "Loose Song"}

    def test_excludes_pycache_dirs(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="albums/__pycache__/ghost.mp3", title="Ghost")
        make_tagged_file(filename="albums/Album/Track.mp3", title="Real Track")

        titles = {f["title"] for f in scan_audio(str(tmp_path))}
        assert "Ghost" not in titles
        assert "Real Track" in titles

    def test_subdirs_none_walks_root_directly(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="loose.mp3", title="Loose")
        files = scan_audio(str(tmp_path), subdirs=None)
        assert len(files) == 1
        assert files[0]["title"] == "Loose"

    def test_fills_missing_title_from_filename_and_artist_from_unknown(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="singles/My Song.mp3")  # no tags set at all
        files = scan_audio(str(tmp_path))
        assert len(files) == 1
        entry = files[0]
        assert entry["title"] == "My Song"
        assert entry["artist"] == "Unknown Artist"

    def test_missing_root_returns_empty_list(self, tmp_path):
        assert scan_audio(str(tmp_path / "does_not_exist")) == []


class TestSafeMove:
    def test_moves_file_creating_parent_dirs(self, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("hello")
        dst = tmp_path / "nested" / "dir" / "dst.txt"
        safe_move(str(src), str(dst))
        assert not src.exists()
        assert dst.read_text() == "hello"

    def test_renames_on_destination_collision(self, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("new")
        dst = tmp_path / "dst.txt"
        dst.write_text("existing")
        safe_move(str(src), str(dst))
        assert dst.read_text() == "existing"
        assert (tmp_path / "dst (2).txt").read_text() == "new"

    def test_noop_when_source_equals_destination(self, tmp_path):
        src = tmp_path / "same.txt"
        src.write_text("content")
        safe_move(str(src), str(src))
        assert src.read_text() == "content"
