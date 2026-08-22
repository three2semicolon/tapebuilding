"""Tests for the normalize_artists plugin."""

import pytest
from organize.normalize_artists import normalize_artist, NormalizeArtistsPlugin


# ----------------------------------------------------------------------
# Unit tests for the normalize_artist() function
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        # Simple single artists
        ("2Pac", "2Pac"),
        ("Dr. Dre", "Dr. Dre"),
        ("Radiohead", "Radiohead"),
        ("", ""),
        ("   ", ""),
        # Featuring variations (case‑insensitive)
        ("Kendrick Lamar feat. SZA", "Kendrick Lamar feat. SZA"),
        ("Kendrick Lamar ft. SZA", "Kendrick Lamar feat. SZA"),
        ("Kendrick Lamar f. SZA", "Kendrick Lamar feat. SZA"),
        ("Kendrick Lamar (feat. SZA)", "Kendrick Lamar feat. SZA"),
        ("SZA feat. Kendrick Lamar", "SZA feat. Kendrick Lamar"),
        ("SZA f. Kendrick Lamar", "SZA feat. Kendrick Lamar"),
        # Two‑artist collaborations
        ("The Beatles & Elvis", "The Beatles & Elvis"),
        ("Aerosmith and AC/DC", "Aerosmith & AC/DC"),
        ("Artists x feat.", "Artists & feat."),
        ("Artist X x Artist Y", "Artist X & Artist Y"),
        # “and” as separator
        ("Artist One and Artist Two", "Artist One & Artist Two"),
        ("feat. and other and", "feat. & other"),
        # Multiple artists (≥3)
        ("A, B, C, D", "A, B, C & D"),
        ("One, Two, Three, Four, Five", "One, Two, Three, Four & Five"),
        # Normalising punctuation / extra spaces
        ("  Artist   &   Artist  ", "Artist & Artist"),
        ("Artist , & Artist", "Artist & Artist"),
        ("Artist &Artist", "Artist & Artist"),
        ("Artist,Artist", "Artist & Artist"),
    ],
)
def test_normalize_artist(raw: str, expected: str) -> None:
    """Validate that normalize_artist produces the expected canonical form."""
    assert normalize_artist(raw) == expected


# ----------------------------------------------------------------------
# Edge‑case unit tests
# ----------------------------------------------------------------------
def test_normalize_artist_edge_cases() -> None:
    """Ensure punctuation and whitespace quirks are handled."""
    # Strip leading/trailing punctuation
    assert normalize_artist("(feat.)") == "feat."
    # Double spaces collapse to a single space internally
    assert normalize_artist("Artist   &   Artist") == "Artist & Artist"
    # Edge punctuation removal
    assert normalize_artist("artist,& artist") == "artist & artist"


# ----------------------------------------------------------------------
# Plugin integration test – verify that the plugin normalises fields
# ----------------------------------------------------------------------
def test_normalize_artists_plugin_mutates_item(monkeypatch) -> None:
    """
    The NormalizeArtistsPlugin listener should update the ``artist`` or
    ``albumartist`` attribute of a beets ``Item`` when the normalized
    representation differs from the original.
    """
    # Mock a minimal beets Item‑like object
    class MockItem:
        def __init__(self, artist: str):
            self.artist = artist
            self.albumartist = None

        def store(self) -> None:
            """Simulate persisting the changes."""
            pass

    # Use monkeypatch to inject the mock into the plugin path
    lib = monkeypatch.MagicMock()
    item = MockItem("Featuring Artist")  # no special formatting, but we test mutation anyway
    lib.item = item

    # Instantiate the plugin and bind its listener to our mock lib
    plugin = NormalizeArtistsPlugin()
    # The plugin registers ``on_item_imported``; we can invoke it directly
    plugin.on_item_imported(lib, item)

    # The plugin should have called ``store`` because the artist field was changed
    # (the exact outcome depends on the plugin’s internal logic; this test ensures no error occurs)
    # As a sanity check, verify that the ``store`` method was called exactly once
    assert item.store.call_count == 1  # type: ignore[attr-defined]