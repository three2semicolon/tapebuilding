"""Functional tests for the downloader module."""
import pathlib
from unittest import mock

import pytest

from tapebuilding import downloader


def test_download_success(tmp_path: pathlib.Path, monkeypatch):
    """Download a single URL and verify the file is written."""
    # Prepare a mock file that would be created by spotdl/yt-dlp
    (tmp_path / "mock.mp3").write_text("hello world")

    # Mock subprocess.run to simulate a successful spotdl download
    mock_result = mock.Mock(
        returncode=0,
        stdout="",
        stderr="",
    )

    def fake_run(cmd, capture_output=True, text=True):
        # Verify that the command looks like a spotdl download call
        assert "spotdl" in " ".join(cmd)
        # Ensure the output directory argument is present
        assert str(tmp_path) in " ".join(cmd)
        return mock_result

    monkeypatch.setattr("subprocess.run", fake_run)

    # Execute the download function
    result = downloader.download(
        urls=["http://example.com/mock.mp3"],
        dest=tmp_path,
        format="mp3",
        bitrate="320k",
        verbose=False,
    )

    # Validate the return value
    assert isinstance(result, list)
    assert len(result) == 1
    downloaded_path = result[0]
    assert isinstance(downloaded_path, pathlib.Path)
    assert downloaded_path.exists()
    assert downloaded_path.read_text() == "hello world"


def test_download_error(tmp_path: pathlib.Path, monkeypatch):
    """Download should handle non‑zero exit codes gracefully."""
    # Simulate spotdl returning a non‑zero exit code
    mock_result = mock.Mock(
        returncode=1,
        stdout="",
        stderr="error message",
    )

    def fake_run(cmd, capture_output=True, text=True):
        assert "spotdl" in " ".join(cmd)
        return mock_result

    monkeypatch.setattr("subprocess.run", fake_run)

    # The function should still return an empty list and not raise
    result = downloader.download(
        urls=["http://example.com/does-not-exist.mp3"],
        dest=tmp_path,
        format="mp3",
        bitrate="320k",
        verbose=False,
    )

    assert result == []