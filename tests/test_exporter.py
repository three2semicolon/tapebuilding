"""Tests for the exporter utilities."""
import csv
import pathlib

import pytest

from tapebuilding.exporter import write_csv, write_manifest


def test_write_csv_atomic(tmp_path: pathlib.Path):
    """write_csv should write atomically and handle special characters."""
    csv_path = tmp_path / "out.csv"
    rows = [
        {"artist": "Test, Band", "title": "Song & More"},
        {"artist": "Another Artist", "title": "Track/123"},
    ]
    fieldnames = ["artist", "title"]

    # Write the CSV
    write_csv(csv_path, rows, fieldnames, write_header=True)

    # Read it back using csv.DictReader to verify content
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows_read = list(reader)

    assert rows_read == [
        {"artist": "Test, Band", "title": "Song & More"},
        {"artist": "Another Artist", "title": "Track/123"},
    ]
    assert csv_path.is_file()


def test_write_csv_without_header(tmp_path: pathlib.Path):
    """write_csv should optionally omit the header."""
    csv_path = tmp_path / "no_header.csv"
    rows = [{"a": "1", "b": "2"}]
    fieldnames = ["a", "b"]

    write_csv(csv_path, rows, fieldnames, write_header=False)

    content = csv_path.read_text(encoding="utf-8")
    # Header line should not be present
    assert not content.startswith("a,b")
    assert "1,2" in content


def test_write_manifest(tmp_path: pathlib.Path):
    """write_manifest should write URLs line‑by‑line."""
    manifest_path = tmp_path / "manifest.txt"
    tracks = [
        {"title": "First Track", "spotify_url": "https://open.spotify.com/track/1"},
        {"title": "Second Track", "spotify_url": "https://open.spotify.com/track/2"},
    ]

    write_manifest(manifest_path, tracks)

    content = manifest_path.read_text(encoding="utf-8")
    assert content == "https://open.spotify.com/track/1\nhttps://open.spotify.com/track/2\n"


def test_write_manifest_filters_empty_urls(tmp_path: pathlib.Path):
    """write_manifest should omit tracks without a URL."""
    manifest_path = tmp_path / "no_urls.txt"
    tracks = [
        {"title": "No URL Track"},
        {"title": "With URL", "spotify_url": "https://example.com/track"},
    ]

    write_manifest(manifest_path, tracks)

    content = manifest_path.read_text(encoding="utf-8")
    assert content.strip() == "https://example.com/track"