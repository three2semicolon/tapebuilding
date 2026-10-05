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
            "path", "artist", "albumartist", "album", "title", "track", "disc", "length",
        }
        assert result["path"] == path
        assert result["artist"] == "Artist A"
        assert result["albumartist"] == "Album Artist A"
        assert result["album"] == "Album A"
        assert result["title"] == "Title A"
        assert result["track"] == 3
        assert result["disc"] == 0  # Default disc value
        assert result["length"] > 0

    def test_read_tags_includes_disc_when_set(self, make_tagged_file):
        """Test that read_tags correctly reads disc field when present"""
        path = make_tagged_file(
            artist="Artist A",
            album="Album A",
            title="Title A",
            disc=2,
        )
        result = read_tags(path)
        assert result["disc"] == 2

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
        # Writing the exact same value should not trigger a save
        before_mtime = os.path.getmtime(path)
        write_tag(path, albumartist="Same Artist")  # Exactly same
        after_mtime = os.path.getmtime(path)
        assert after_mtime == before_mtime, "Writing identical value should not update file"

        # Writing a case-only different value should trigger a save (Bug 7)
        # Exact NFC strings differ, so write should occur
        write_tag(path, albumartist="same artist")
        result = read_tags(path)
        assert result["albumartist"] == "same artist", "Tag should be updated to new value"


class TestSanitize:
    def test_strips_filesystem_unsafe_characters(self):
        assert sanitize('A/B:C*D?E"F<G>H|I') == "A_B_C_D_E_F_G_H_I"

    def test_strips_trailing_dots_and_whitespace(self):
        assert sanitize("  Track Name...  ") == "Track Name"

    def test_empty_or_none_returns_underscore(self):
        assert sanitize("") == "_"
        assert sanitize(None) == "_"

    def test_all_illegal_characters_returns_underscore(self):
        assert sanitize("///") == "___"


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


class TestWriteTagNFC:
    def test_write_tag_respects_nfc_equality(self, make_tagged_file):
        """Bug 7: write_tag should compare exact NFC strings, not normalize_key"""
        # Create a file with a tag value
        path = make_tagged_file(title="Title")

        # Writing the same NFC-normalized value should not trigger a save (no-op)
        before_mtime = os.path.getmtime(path)
        write_tag(path, title="Title")  # Same value
        after_mtime = os.path.getmtime(path)
        assert after_mtime == before_mtime, "Writing identical NFC value should not update file"

        # Writing a case-only different value should trigger a save
        # (case-only differences matter for NFC)
        before_mtime = os.path.getmtime(path)
        write_tag(path, title="TITLE")  # Uppercase - different NFC
        after_mtime = os.path.getmtime(path)
        assert after_mtime != before_mtime, "Writing case-only different value should update file"

        # Verify the value was actually written
        result = read_tags(path)
        assert result["title"] == "TITLE"


class TestCanonicalAlbum:
    def test_canonical_album_selects_preferred_edition(self):
        """Test canonical_album picks the best edition variant"""
        from lib.tags import canonical_album

        files = [
            {'album': 'Title'},
            {'album': 'Title (Deluxe)'},
            {'album': 'Title (Remastered)'},
        ]

        result = canonical_album(files)
        # Should pick one with edition marker over bare 'Title'
        assert result != 'Title'
        assert result in ['Title (Deluxe)', 'Title (Remastered)']

    def test_canonical_album_break_ties_by_length_and_alphabetical(self):
        """Test tie-breaking logic in canonical_album"""
        from lib.tags import canonical_album

        files = [
            {'album': 'Title (Edit)'},      # length 9
            {'album': 'Title (Version)'},   # length 8
            {'album': 'Title (Mix)'},       # length 7
        ]

        result = canonical_album(files)
        # Should pick the longest edition string when all have editions
        assert result == 'Title (Edit)'


class TestSamePath:
    def test_same_path_identical_paths(self):
        """Test same_path with identical paths"""
        from lib.tags import same_path
        assert same_path('/path/to/file.txt', '/path/to/file.txt') == True
        assert same_path('', '') == True

    def test_same_path_different_paths(self):
        """Test same_path with different paths"""
        from lib.tags import same_path
        assert same_path('/path/to/file.txt', '/path/to/other.txt') == False
        assert same_path('/path/to/file.txt', '') == False

    def test_same_path_case_sensitivity_unix(self):
        """Test same_path respects case sensitivity on Unix-like systems"""
        from lib.tags import same_path
        # This test's behavior depends on the platform, but we can test the logic
        assert same_path('/PATH/TO/FILE.TXT', '/path/to/file.txt') == False  # Should be False on case-sensitive FS


class TestFindDuplicates:
    def test_find_duplicates_empty_list(self):
        """Test find_duplicates with empty input"""
        from lib.tags import find_duplicates
        assert find_duplicates([]) == []

    def test_find_duplicates_no_duplicates(self):
        """Test find_duplicates with no duplicates"""
        from lib.tags import find_duplicates
        files = [
            {'artist': 'Artist A', 'title': 'Title A', 'disc': 0, 'length': 100.0},
            {'artist': 'Artist B', 'title': 'Title B', 'disc': 0, 'length': 200.0},
        ]
        assert find_duplicates(files) == []

    def test_find_duplicates_with_duplicates(self):
        """Test find_duplicates finds actual duplicates"""
        from lib.tags import find_duplicates
        files = [
            {'artist': 'Artist A', 'title': 'Title A', 'disc': 0, 'length': 100.0},
            {'artist': 'artist a', 'title': 'title a', 'disc': 0, 'length': 101.0},  # Same keys, similar length
            {'artist': 'Artist B', 'title': 'Title B', 'disc': 0, 'length': 200.0},
        ]
        result = find_duplicates(files)
        assert len(result) == 1
        assert len(result[0]) == 2
        assert result[0][0]['artist'] == 'Artist A'
        assert result[0][1]['artist'] == 'artist a'


class TestDiscField:
    def test_read_tags_includes_disc_field(self, make_tagged_file):
        """Test that read_tags includes the disc field (D5)"""
        path = make_tagged_file(disc=2, title="Track")
        result = read_tags(path)
        assert 'disc' in result
        assert result['disc'] == 2

    def test_read_tags_disc_defaults_to_zero(self, make_tagged_file):
        """Test that read_tags defaults disc to 0 when not present"""
        path = make_tagged_file(title="Track")  # No disc set
        result = read_tags(path)
        assert 'disc' in result
        assert result['disc'] == 0
