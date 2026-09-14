"""Tests for lib.paths - TEST_PLANS.md 'lib/paths.py' section.

Written against the actual current source. This is the one place every
root path in the project gets resolved, so precedence order and the
required-vs-fallback split matter more here than almost anywhere else in
the repo.
"""
import os

import pytest

from lib.paths import resolve, archive_path, tapedeck_path, playlists_path, exports_dir, ffmpeg_path


class TestResolve:
    def test_cli_overrides_env_and_default(self, monkeypatch):
        monkeypatch.setenv("SOME_PATH", "/from/env")
        assert resolve("SOME_PATH", cli="/from/cli", default="/from/default") == "/from/cli"

    def test_env_overrides_default(self, monkeypatch):
        monkeypatch.setenv("SOME_PATH", "/from/env")
        assert resolve("SOME_PATH", cli=None, default="/from/default") == "/from/env"

    def test_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("SOME_PATH", raising=False)
        assert resolve("SOME_PATH", cli=None, default="/from/default") == "/from/default"

    def test_required_raises_when_nothing_resolves(self, monkeypatch):
        monkeypatch.delenv("SOME_PATH", raising=False)
        with pytest.raises(ValueError):
            resolve("SOME_PATH", cli=None, default=None, required=True)

    def test_required_does_not_raise_when_resolved(self, monkeypatch):
        monkeypatch.setenv("SOME_PATH", "/from/env")
        # should not raise
        assert resolve("SOME_PATH", cli=None, default=None, required=True) == "/from/env"


class TestArchivePath:
    def test_uses_env_when_set(self, monkeypatch):
        monkeypatch.setenv("ARCHIVE_PATH", "/my/archive")
        assert archive_path() == "/my/archive"

    def test_cli_override_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("ARCHIVE_PATH", "/my/archive")
        assert archive_path(cli="/explicit/path") == "/explicit/path"

    def test_has_convenience_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("ARCHIVE_PATH", raising=False)
        # archive_path() is documented to have a fallback - it should
        # NOT raise even with nothing set.
        result = archive_path()
        assert result  # some non-empty default, not an error


class TestPlaylistsPath:
    def test_required_no_fallback(self, monkeypatch):
        monkeypatch.delenv("PLAYLISTS_PATH", raising=False)
        with pytest.raises(ValueError):
            playlists_path()

    def test_uses_env_when_set(self, monkeypatch):
        monkeypatch.setenv("PLAYLISTS_PATH", "/my/playlists")
        assert playlists_path() == "/my/playlists"


class TestTapedeckPath:
    def test_has_convenience_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("TAPEDECK_PATH", raising=False)
        result = tapedeck_path()
        assert result


class TestExportsDir:
    def test_explicit_cli_path_is_created_and_returned(self, tmp_path):
        target = tmp_path / "explicit_exports"
        assert not target.exists()
        result = exports_dir(cli=str(target))
        assert result == str(target)
        assert target.is_dir()

    def test_derives_from_playlists_path_and_creates_subdir(self, tmp_path, monkeypatch):
        base = tmp_path / "playlists_root"
        base.mkdir()
        monkeypatch.setenv("PLAYLISTS_PATH", str(base))
        result = exports_dir()
        assert result == os.path.join(str(base), "exports")
        assert os.path.isdir(result)

    def test_explicit_playlists_path_value_param(self, tmp_path):
        base = tmp_path / "given_playlists_root"
        base.mkdir()
        result = exports_dir(playlists_path_value=str(base))
        assert result == os.path.join(str(base), "exports")
        assert os.path.isdir(result)


class TestFfmpegPath:
    def test_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("FFMPEG_PATH", raising=False)
        assert ffmpeg_path() is None

    def test_uses_env_when_set(self, monkeypatch):
        monkeypatch.setenv("FFMPEG_PATH", "/opt/ffmpeg/bin")
        assert ffmpeg_path() == "/opt/ffmpeg/bin"

    def test_cli_override(self, monkeypatch):
        monkeypatch.setenv("FFMPEG_PATH", "/opt/ffmpeg/bin")
        assert ffmpeg_path(cli="/other/ffmpeg") == "/other/ffmpeg"
