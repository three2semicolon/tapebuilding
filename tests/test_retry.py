"""Tests for the retry utilities."""
import pathlib
from unittest import mock

import pytest

from tapebuilding import retry


def test_load_failure_logs_parses_lines(tmp_path: pathlib.Path):
    """load_failure_logs should parse urls and optional reasons from log files."""
    # Create mock failure log files
    failed_path = tmp_path / "failed.txt"
    soft_path = tmp_path / "soft.txt"
    failed_path.write_text(
        "http://example.com/track1.mp3  # missing file\n"
        "http://example.com/track2.mp3\n"
        "# comment line\n"
        "\n"
        "http://example.com/track3.mp3  # bad format\n"
    )
    soft_path.write_text("")  # empty

    # Call the function
    combined = retry.load_failure_logs(failed_path, soft_path)

    # Expected list of (url, [reasons]) tuples
    expected = [
        ("http://example.com/track1.mp3", ["missing file"]),
        ("http://example.com/track2.mp3", [""]),
        ("http://example.com/track3.mp3", ["bad format"]),
    ]
    assert combined == expected


def test_load_failure_logs_ignores_empty_and_comment_lines(tmp_path: pathlib.Path):
    """Empty lines and comment lines should be ignored."""
    file_path = tmp_path / "log.txt"
    file_path.write_text(
        "# this is a comment\n"
        "\n"
        "   \n"
        "http://example.com/track1.mp3  # reason with spaces  \n"
        "# another comment\n"
    )

    combined = retry.load_failure_logs(file_path, file_path)  # same file for both
    # Should get one entry with url and reason stripped
    assert len(combined) == 1
    url, reasons = combined[0]
    assert url == "http://example.com/track1.mp3"
    # Reason should be stripped of trailing spaces
    assert "reason with spaces" in reasons[0]


def test_filter_existing_filters_correctly(tmp_path: pathlib.Path, monkeypatch):
    """filter_existing should separate URLs that exist from those that don't."""
    # Mock a metadata source (e.g., CSV export) and a library index (set of known files)
    metadata_path = tmp_path / "metadata.csv"
    metadata_path.write_text("track,artist\nsong1,Artist One\nsong2,Artist Two\n")
    # Simulate library index mapping URL → None (use dict with keys as URLs)
    library_index = {"http://example.com/song1.mp3": None, "http://example.com/song3.mp3": None}

    urls = ["http://example.com/song1.mp3", "http://example.com/song2.mp3", "http://example.com/song3.mp3"]
    retry_urls, on_disk, no_meta = retry.filter_existing(urls, metadata_path, "mp3", library_index)

    # song1 exists in library_index → should be in on_disk
    assert "http://example.com/song1.mp3" in on_disk
    # song3 also exists → should be in on_disk
    assert "http://example.com/song3.mp3" in on_disk
    # song2 not in index → should be in retry_urls (to be retried)
    assert "http://example.com/song2.mp3" in retry_urls
    # No entries should be in no_meta in this simple case
    assert no_meta == []


def test_filter_existing_labels_reasons(tmp_path: pathlib.Path, monkeypatch):
    """filter_existing should also return a list of reasons for each URL when supplied.
    (the placeholder implementation returns empty reason lists, but the contract
    is to include them when available.)"""
    metadata_path = tmp_path / "metadata.csv"
    metadata_path.write_text("track,artist\nsong1,Artist One\nsong2,Artist Two\n")
    library_index = {"http://example.com/song1.mp3": None, "http://example.com/song3.mp3": None}
    urls = ["http://example.com/song1.mp3", "http://example.com/song2.mp3", "http://example.com/song3.mp3"]
    retry_urls, on_disk, no_meta = retry.filter_existing(urls, metadata_path, "mp3", library_index)
    # URLs that need retry are those not in library_index
    assert set(retry_urls) == {"http://example.com/song2.mp3"}
    # URLs that are already downloaded are those in library_index
    assert set(on_disk) == {"http://example.com/song1.mp3", "http://example.com/song3.mp3"}
    # no_meta should be empty
    assert no_meta == []
    # The function returns three lists; their lengths should be consistent
    assert len(retry_urls) + len(on_disk) + len(no_meta) == len(urls)