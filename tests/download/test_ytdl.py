"""Tests for download.ytdl - TEST_PLANS.md 'download/ytdl.py' section.
Written against the actual current source.
"""
import sys
import types
from unittest import mock

import pytest

from download.ytdl import is_playlist_url, download_ytdl, OUTTMPL_SINGLE, OUTTMPL_PLAYLIST


class TestIsPlaylistUrl:
    @pytest.mark.parametrize("url", [
        "https://soundcloud.com/artist/sets/my-set",
        "https://soundcloud.com/artist/sets/",
        "https://soundcloud.com/artist/albums/some-album",
        "https://soundcloud.com/artist/tracks",
        "https://soundcloud.com/artist/tracks/",
        "https://soundcloud.com/artist/likes",
        "https://soundcloud.com/artist/reposts",
    ])
    def test_recognizes_playlist_shapes(self, url):
        assert is_playlist_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://soundcloud.com/artist/a-single-track",
        "https://www.youtube.com/watch?v=HG4P8snWyvM",
        "https://youtu.be/HG4P8snWyvM",
    ])
    def test_does_not_flag_single_tracks(self, url):
        assert is_playlist_url(url) is False


class FakeYoutubeDL:
    """Minimal stand-in for yt_dlp.YoutubeDL, injected via sys.modules so
    download_ytdl()'s internal `import yt_dlp` picks this up instead of
    hitting the network.
    """
    last_instance = None

    def __init__(self, opts):
        self.opts = opts
        self.download_calls = []
        FakeYoutubeDL.last_instance = self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        return {"entries": [{"title": "Fake Track One"}, {"title": "Fake Track Two"}]}

    def download(self, urls):
        self.download_calls.append(urls)
        return 0


@pytest.fixture
def fake_yt_dlp(monkeypatch):
    fake_module = types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)
    return fake_module


class TestDownloadYtdlMetadataOnly:
    def test_metadata_only_does_not_call_download(self, fake_yt_dlp, capsys, tmp_path):
        result = download_ytdl(
            "https://www.youtube.com/watch?v=abc",
            output_dir=str(tmp_path),
            metadata_only=True,
        )
        assert result is True
        assert FakeYoutubeDL.last_instance.download_calls == []

    def test_metadata_only_prints_track_titles(self, fake_yt_dlp, capsys, tmp_path):
        download_ytdl(
            "https://www.youtube.com/watch?v=abc",
            output_dir=str(tmp_path),
            metadata_only=True,
        )
        out = capsys.readouterr().out
        assert "Fake Track One" in out


class TestDownloadYtdlTemplateSelection:
    def test_single_url_uses_single_template(self, fake_yt_dlp, tmp_path):
        download_ytdl("https://www.youtube.com/watch?v=abc", output_dir=str(tmp_path))
        opts = FakeYoutubeDL.last_instance.opts
        assert OUTTMPL_SINGLE.split("/")[-1] in opts["outtmpl"] or OUTTMPL_SINGLE in opts["outtmpl"]

    def test_playlist_url_uses_playlist_template(self, fake_yt_dlp, tmp_path):
        download_ytdl("https://soundcloud.com/artist/sets/my-set", output_dir=str(tmp_path))
        opts = FakeYoutubeDL.last_instance.opts
        assert "%(playlist)s" in opts["outtmpl"]


class TestDownloadYtdlFfmpegResolution:
    def test_explicit_ffmpeg_param_is_used(self, fake_yt_dlp, tmp_path, monkeypatch):
        # even if FFMPEG_PATH env is set differently, the explicit --ffmpeg
        # arg (download_ytdl's own ffmpeg_path param) should win.
        monkeypatch.setenv("FFMPEG_PATH", "/env/ffmpeg")
        download_ytdl(
            "https://www.youtube.com/watch?v=abc",
            output_dir=str(tmp_path),
            ffmpeg_path="/explicit/ffmpeg",
        )
        opts = FakeYoutubeDL.last_instance.opts
        assert opts.get("ffmpeg_location") == "/explicit/ffmpeg"

    def test_falls_back_to_env_when_not_explicit(self, fake_yt_dlp, tmp_path, monkeypatch):
        monkeypatch.setenv("FFMPEG_PATH", "/env/ffmpeg")
        download_ytdl("https://www.youtube.com/watch?v=abc", output_dir=str(tmp_path))
        opts = FakeYoutubeDL.last_instance.opts
        assert opts.get("ffmpeg_location") == "/env/ffmpeg"


class TestDownloadYtdlMissingDependency:
    def test_missing_yt_dlp_prints_error_and_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "yt_dlp", None)  # forces ImportError on `import yt_dlp`
        result = download_ytdl("https://www.youtube.com/watch?v=abc", output_dir=str(tmp_path))
        assert result is False
