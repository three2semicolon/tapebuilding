"""Shared fixtures for tests under tests/download/.

RECONSTRUCTED, NOT FROM AN ORIGINAL: test_retry.py and
test_spotify_download.py both already reference sample_manifest_csv and
fixture_library, but no tests/download/conftest.py existed to define
them - this was inferred purely from how those two files use the
fixtures. Double-check the shape below actually matches what you had in
mind (or had already written) before relying on it.

sample_manifest_csv / fixture_library are a paired setup for the
--pre-skip-existing / retry.py library-recheck consistency tests:
- AAA's (artist, track) -> predict_output_filename('Test Artist',
  'Test Track', 'mp3') == 'Test Artist - Test Track.mp3', which
  fixture_library is pre-seeded with, so it should read as
  already-on-disk.
- BBB is deliberately NOT seeded anywhere in fixture_library, so it
  should read as new / not-on-disk.
"""
import pytest


@pytest.fixture
def sample_manifest_csv(tmp_path):
    """A two-row CSV shaped like a real spotify_manifest.csv /
    playlists_manifest.csv export (spotify_url, artist_names,
    track_name, album_name columns)."""
    csv_path = tmp_path / "spotify_manifest.csv"
    csv_path.write_text(
        "spotify_url,artist_names,track_name,album_name\n"
        "https://open.spotify.com/track/AAA,Test Artist,Test Track,Test Album\n"
        "https://open.spotify.com/track/BBB,Second Artist,Second Track,Second Album\n",
        encoding="utf-8",
    )
    return csv_path


@pytest.fixture
def fixture_library(tmp_path):
    """A minimal 'already downloaded' library directory. Content doesn't
    matter - download.existing's checks are filename-only - so the file
    is empty, just present under the exact predicted filename for
    sample_manifest_csv's AAA row."""
    library_root = tmp_path / "library"
    library_root.mkdir()
    (library_root / "Test Artist - Test Track.mp3").write_bytes(b"")
    return library_root
