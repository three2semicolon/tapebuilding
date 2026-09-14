"""Tests for download.spotify_download - TEST_PLANS.md
'download/spotify_download.py' section. Written against the actual
current source.

subprocess.Popen is mocked throughout - these tests never shell out to a
real spotdl.
"""
import os
from unittest import mock

import pytest

from download.spotify_download import download_spotify, _extract_urls_from_csv, _log_urls


class TestExtractUrlsFromCsv:
    def test_reads_spotify_url_column(self, tmp_path):
        csv_path = tmp_path / "urls.csv"
        csv_path.write_text(
            "spotify_url,other_col\n"
            "https://open.spotify.com/track/AAA,ignored\n"
            "https://open.spotify.com/track/BBB,ignored\n",
            encoding="utf-8",
        )
        urls = _extract_urls_from_csv(str(csv_path))
        assert urls == [
            "https://open.spotify.com/track/AAA",
            "https://open.spotify.com/track/BBB",
        ]

    def test_skips_blank_urls(self, tmp_path):
        csv_path = tmp_path / "urls.csv"
        csv_path.write_text("spotify_url\n\nhttps://x\n", encoding="utf-8")
        assert _extract_urls_from_csv(str(csv_path)) == ["https://x"]

    def test_missing_file_returns_empty_list(self, tmp_path):
        assert _extract_urls_from_csv(str(tmp_path / "nope.csv")) == []


class TestLogUrls:
    def test_appends_url_with_reason(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _log_urls("failed.txt", ["https://x"], reason="track_unavailable")
        content = (tmp_path / "failed.txt").read_text(encoding="utf-8")
        assert "https://x  # track_unavailable" in content

    def test_appends_bare_url_without_reason(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _log_urls("failed.txt", ["https://x"])
        content = (tmp_path / "failed.txt").read_text(encoding="utf-8")
        assert content.strip() == "https://x"

    def test_appends_rather_than_overwrites(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _log_urls("failed.txt", ["https://a"])
        _log_urls("failed.txt", ["https://b"])
        lines = (tmp_path / "failed.txt").read_text(encoding="utf-8").splitlines()
        assert lines == ["https://a", "https://b"]


class TestDownloadSpotifyUrlHandling:
    def test_missing_url_file_returns_false(self, tmp_path):
        result = download_spotify(str(tmp_path / "does_not_exist.txt"))
        assert result is False

    def test_empty_url_file_returns_false(self, tmp_path):
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        result = download_spotify(str(empty))
        assert result is False

    def test_deduplicates_urls_preserving_order(self, tmp_path, monkeypatch):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://a\nhttps://b\nhttps://a\n", encoding="utf-8")

        captured_cmds = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            proc = mock.Mock()
            proc.stdout = iter(["batch downloaded successfully\n"])
            proc.wait.return_value = None
            proc.returncode = 0
            return proc

        monkeypatch.setattr("download.spotify_download.subprocess.Popen", fake_popen)
        download_spotify(str(url_file), output_dir=str(tmp_path / "out"), batch_size=10)

        # only one batch, containing the deduped 2 urls, in first-seen order
        assert len(captured_cmds) == 1
        cmd = captured_cmds[0]
        assert "https://a" in cmd
        assert "https://b" in cmd
        assert cmd.count("https://a") == 1


class TestDownloadSpotifyBatching:
    def _fake_popen_success(self, monkeypatch):
        captured = []

        def fake_popen(cmd, **kwargs):
            captured.append(cmd)
            proc = mock.Mock()
            proc.stdout = iter(["batch downloaded successfully\n"])
            proc.wait.return_value = None
            proc.returncode = 0
            return proc

        monkeypatch.setattr("download.spotify_download.subprocess.Popen", fake_popen)
        return captured

    def test_batch_size_splits_urls_into_correct_number_of_batches(self, tmp_path, monkeypatch):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("\n".join(f"https://track/{i}" for i in range(5)), encoding="utf-8")
        captured = self._fake_popen_success(monkeypatch)

        download_spotify(str(url_file), output_dir=str(tmp_path / "out"), batch_size=2)

        # 5 urls / batch_size 2 -> 3 batches (2, 2, 1)
        assert len(captured) == 3


class TestDownloadSpotifyFailureClassification:
    def _fake_popen_with_output(self, output_line, returncode=0):
        def fake_popen(cmd, **kwargs):
            proc = mock.Mock()
            proc.stdout = iter([output_line])
            proc.wait.return_value = None
            proc.returncode = returncode
            return proc
        return fake_popen

    def test_hard_failure_marker_logs_to_failed_and_does_not_retry(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://gone\n", encoding="utf-8")

        popen_mock = mock.Mock(side_effect=self._fake_popen_with_output("Track no longer exists\n"))
        monkeypatch.setattr("download.spotify_download.subprocess.Popen", popen_mock)

        download_spotify(str(url_file), output_dir=str(tmp_path / "out"), retries=3)

        # hard failure should not retry - Popen called exactly once despite retries=3
        assert popen_mock.call_count == 1
        assert (tmp_path / "failed_downloads.txt").exists()
        assert "track_unavailable" in (tmp_path / "failed_downloads.txt").read_text(encoding="utf-8")

    def test_soft_failure_marker_retries_then_logs_to_soft(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://flaky\n", encoding="utf-8")

        popen_mock = mock.Mock(side_effect=self._fake_popen_with_output("No results found\n"))
        monkeypatch.setattr("download.spotify_download.subprocess.Popen", popen_mock)
        monkeypatch.setattr("download.spotify_download.time.sleep", lambda s: None)

        download_spotify(str(url_file), output_dir=str(tmp_path / "out"), retries=2, retry_delay=0)

        # soft failure retries up to `retries` -> 1 initial + 2 retries = 3 calls
        assert popen_mock.call_count == 3
        assert (tmp_path / "soft_failures.txt").exists()

    def test_success_does_not_write_any_failure_log(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://good\n", encoding="utf-8")

        popen_mock = mock.Mock(side_effect=self._fake_popen_with_output("batch downloaded successfully\n"))
        monkeypatch.setattr("download.spotify_download.subprocess.Popen", popen_mock)

        result = download_spotify(str(url_file), output_dir=str(tmp_path / "out"))

        assert result is True
        assert not (tmp_path / "failed_downloads.txt").exists()
        assert not (tmp_path / "soft_failures.txt").exists()


class TestDownloadSpotifyPreSkipExisting:
    def test_validate_only_reports_and_returns_without_downloading(self, tmp_path, sample_manifest_csv, fixture_library, monkeypatch):
        popen_mock = mock.Mock()
        monkeypatch.setattr("download.spotify_download.subprocess.Popen", popen_mock)

        result = download_spotify(
            str(sample_manifest_csv),
            output_dir=str(fixture_library),
            pre_skip_existing=True,
            validate_only=True,
        )

        assert result is True
        popen_mock.assert_not_called()

    def test_pre_skip_existing_skips_already_downloaded_track(self, tmp_path, sample_manifest_csv, fixture_library, monkeypatch):
        """fixture_library already contains 'Test Artist - Test Track.mp3',
        matching sample_manifest_csv's first row - only the second URL
        should actually get downloaded.
        """
        captured_cmds = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            proc = mock.Mock()
            proc.stdout = iter(["batch downloaded successfully\n"])
            proc.wait.return_value = None
            proc.returncode = 0
            return proc

        monkeypatch.setattr("download.spotify_download.subprocess.Popen", fake_popen)

        download_spotify(
            str(sample_manifest_csv),
            output_dir=str(fixture_library),
            pre_skip_existing=True,
        )

        assert len(captured_cmds) == 1
        assert "https://open.spotify.com/track/BBB" in captured_cmds[0]
        assert "https://open.spotify.com/track/AAA" not in captured_cmds[0]

    def test_no_csv_metadata_available_skips_existence_check_with_warning(self, tmp_path, capsys, monkeypatch):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://x\n", encoding="utf-8")

        popen_mock = mock.Mock()
        monkeypatch.setattr("download.spotify_download.subprocess.Popen",
                             lambda cmd, **kw: mock.Mock(
                                 stdout=iter(["batch downloaded successfully\n"]),
                                 wait=lambda: None, returncode=0))

        download_spotify(str(url_file), output_dir=str(tmp_path / "out"), pre_skip_existing=True)
        out = capsys.readouterr().out
        assert "skipping existence check" in out.lower()
