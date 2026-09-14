"""Tests for download.manifest - TEST_PLANS.md 'download/manifest.py'
section. HIGHEST PRIORITY module in this package: it was reconstructed
this session, not carried forward from a verified original, and the
'album' column guess specifically is unverified against a real export.

Written against the actual current source (reconstructed in this
session's earlier turns).
"""
import csv

import pytest

from download.manifest import (
    sanitize_filename,
    predict_output_filename,
    read_csv_metadata_from_file,
    read_csv_metadata,
)


class TestSanitizeFilename:
    def test_strips_windows_reserved_characters(self):
        assert sanitize_filename('a<b>c:d"e/f\\g|h?i*j') == "abcdefghij"

    def test_strips_control_characters(self):
        assert sanitize_filename("abc\x00\x1fdef") == "abcdef"

    def test_strips_leading_trailing_dots_and_spaces(self):
        assert sanitize_filename("  . Song Name . ") == "Song Name"

    def test_leaves_normal_characters_untouched(self):
        assert sanitize_filename("Artist Name - Song Title") == "Artist Name - Song Title"


class TestPredictOutputFilename:
    def test_basic_shape(self):
        assert predict_output_filename("Some Artist", "Some Track", "mp3") == "Some Artist - Some Track.mp3"

    def test_sanitizes_the_combined_string(self):
        result = predict_output_filename("A/B", "C:D", "mp3")
        assert "/" not in result
        assert ":" not in result

    def test_matches_a_real_downloaded_filename_shape(self):
        """This is the test that actually matters per TEST_PLANS.md: once
        you have a real spotdl-downloaded file on disk, replace this
        assertion with the literal filename spotdl actually wrote for a
        known (artist, track) pair, and confirm predict_output_filename()
        reproduces it exactly. As written this only checks internal
        consistency, not agreement with the real tool.
        """
        predicted = predict_output_filename("Test Artist", "Test Track", "mp3")
        assert predicted == "Test Artist - Test Track.mp3"  # TODO: replace with a real spotdl filename


class TestReadCsvMetadataFromFile:
    def test_requires_track_name_and_artist_names_columns(self, tmp_path):
        csv_path = tmp_path / "bad.csv"
        csv_path.write_text("spotify_url,artist_names\nhttps://x,Artist\n", encoding="utf-8")
        assert read_csv_metadata_from_file(str(csv_path)) == {}

    def test_reads_artist_track_album(self, sample_manifest_csv):
        result = read_csv_metadata_from_file(str(sample_manifest_csv))
        assert result["https://open.spotify.com/track/AAA"] == {
            "artist": "Test Artist",
            "track": "Test Track",
            "album": "Test Album",
        }

    def test_missing_album_column_gives_empty_string_not_error(self, tmp_path):
        csv_path = tmp_path / "no_album.csv"
        csv_path.write_text(
            "spotify_url,artist_names,track_name\n"
            "https://x,Artist,Track\n",
            encoding="utf-8",
        )
        result = read_csv_metadata_from_file(str(csv_path))
        assert result["https://x"]["album"] == ""

    def test_falls_back_to_album_column_if_album_name_absent(self, tmp_path):
        """Covers the second half of the album-column guess
        (`row.get('album_name') or row.get('album')`) - if your real
        export uses a plain 'album' header instead of 'album_name', this
        is the behavior that currently saves you; delete this test once
        you've confirmed which header the real export actually uses and
        simplified manifest.py accordingly.
        """
        csv_path = tmp_path / "alt_album_header.csv"
        csv_path.write_text(
            "spotify_url,artist_names,track_name,album\n"
            "https://x,Artist,Track,Fallback Album\n",
            encoding="utf-8",
        )
        result = read_csv_metadata_from_file(str(csv_path))
        assert result["https://x"]["album"] == "Fallback Album"

    def test_blank_url_rows_are_skipped(self, tmp_path):
        csv_path = tmp_path / "blank_url.csv"
        csv_path.write_text(
            "spotify_url,artist_names,track_name\n"
            ",Artist,Track\n",
            encoding="utf-8",
        )
        assert read_csv_metadata_from_file(str(csv_path)) == {}

    def test_nonexistent_file_returns_empty_dict_not_raise(self, tmp_path):
        assert read_csv_metadata_from_file(str(tmp_path / "does_not_exist.csv")) == {}


class TestReadCsvMetadata:
    def test_single_csv_file(self, sample_manifest_csv):
        result = read_csv_metadata(str(sample_manifest_csv))
        assert len(result) == 2

    def test_directory_merges_first_seen_wins(self, tmp_path):
        (tmp_path / "a.csv").write_text(
            "spotify_url,artist_names,track_name\n"
            "https://dup,First Artist,First Track\n",
            encoding="utf-8",
        )
        (tmp_path / "b.csv").write_text(
            "spotify_url,artist_names,track_name\n"
            "https://dup,Second Artist,Second Track\n"
            "https://unique,Unique Artist,Unique Track\n",
            encoding="utf-8",
        )
        result = read_csv_metadata(str(tmp_path))
        # first-seen-wins is glob-order dependent for the duplicate - assert
        # only that ONE of the two versions won, consistently, and that the
        # unique entry made it through regardless.
        assert result["https://dup"]["artist"] in ("First Artist", "Second Artist")
        assert result["https://unique"]["artist"] == "Unique Artist"

    def test_non_csv_non_directory_returns_empty_dict(self, tmp_path):
        txt_path = tmp_path / "urls.txt"
        txt_path.write_text("https://example.com\n", encoding="utf-8")
        assert read_csv_metadata(str(txt_path)) == {}

    def test_always_returns_dict_never_none(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = read_csv_metadata(str(empty_dir))
        assert isinstance(result, dict)
        assert result == {}
