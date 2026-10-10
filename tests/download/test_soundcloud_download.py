"""Tests for download.soundcloud_download - TEST_PLANS.md
'download/soundcloud_download.py' section. Written against the actual
current source.

subprocess.Popen is mocked throughout - these tests never shell out to a
real ytdl.
"""
import os
from unittest import mock

import pytest

from download.soundcloud.soundcloud_download import download_soundcloud, _predict_soundcloud_filename


class TestPredictSoundcloudFilename:
    def test_predict_single_track_filename(self):
        """Test filename prediction for a single track (no set info)."""
        filename = _predict_soundcloud_filename(
            artist="Artist Name",
            track="Track Title",
            fmt="mp3"
        )
        assert filename == "Artist Name - Track Title.mp3"

    def test_predict_playlist_track_filename(self):
        """Test filename prediction for a track in a set/playlist."""
        filename = _predict_soundcloud_filename(
            artist="Artist Name",
            track="Track Title",
            set_name="My Set",
            set_position=1,
            fmt="mp3"
        )
        assert filename == "My Set/01 - Artist Name - Track Title.mp3"

    def test_predict_playlist_track_filename_zero_padded(self):
        """Test filename prediction with proper zero-padding for track numbers >= 10."""
        filename = _predict_soundcloud_filename(
            artist="Artist",
            track="Track",
            set_name="Album",
            set_position=10,
            fmt="flac"
        )
        assert filename == "Album/10 - Artist - Track.flac"


class TestDownloadSoundcloudUrlHandling:
    def test_missing_url_file_returns_false(self, tmp_path):
        result = download_soundcloud(str(tmp_path / "does_not_exist.txt"))
        assert result is False

    def test_empty_url_file_returns_false(self, tmp_path):
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        result = download_soundcloud(str(empty))
        assert result is False


class TestDownloadSoundcloudBatching:
    def _fake_ytdl_success(self, monkeypatch):
        captured = []

        def fake_download_ytdl(url, **kwargs):
            captured.append((url, kwargs))
            # Return True to indicate success
            return True

        monkeypatch.setattr("download.soundcloud.soundcloud_download.download_ytdl", fake_download_ytdl)
        return captured

    def test_each_url_gets_individual_ytdl_call(self, tmp_path, monkeypatch):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("\n".join(f"https://soundcloud.com/artist/track{i}" for i in range(5)), encoding="utf-8")
        captured = self._fake_ytdl_success(monkeypatch)

        download_soundcloud(str(url_file), output_dir=str(tmp_path / "out"), batch_size=2)

        # Each URL should get its own download_ytdl call regardless of batch_size
        assert len(captured) == 5
        # Check that all URLs were processed
        all_urls = [url for url, _ in captured]
        expected_urls = [f"https://soundcloud.com/artist/track{i}" for i in range(5)]
        assert sorted(all_urls) == sorted(expected_urls)


class TestDownloadSoundcloudFailureHandling:
    def test_ytdl_failure_results_in_false_return(self, tmp_path, monkeypatch):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://soundcloud.com/artist/track\n", encoding="utf-8")

        def fake_download_ytdl(url, **kwargs):
            return False  # ytdl failed

        monkeypatch.setattr("download.soundcloud.soundcloud_download.download_ytdl", fake_download_ytdl)

        result = download_soundcloud(str(url_file), output_dir=str(tmp_path / "out"))
        assert result is False

    def test_ytdl_success_results_in_true_return(self, tmp_path, monkeypatch):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://soundcloud.com/artist/track\n", encoding="utf-8")

        def fake_download_ytdl(url, **kwargs):
            return True  # ytdl succeeded

        monkeypatch.setattr("download.soundcloud.soundcloud_download.download_ytdl", fake_download_ytdl)

        result = download_soundcloud(str(url_file), output_dir=str(tmp_path / "out"))
        assert result is True