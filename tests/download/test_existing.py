"""Tests for download.existing - TEST_PLANS.md 'download/existing.py'
section. resolve_output_dir() was missing entirely until this session -
written against the patched source.
"""
import os

import pytest

from download.existing import resolve_output_dir, build_library_index, scan_existing_fuzzy


class TestResolveOutputDir:
    def test_cli_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARCHIVE_PATH", str(tmp_path / "env_archive"))
        explicit = tmp_path / "explicit"
        result = resolve_output_dir(str(explicit))
        assert result == str(explicit)

    def test_falls_back_to_archive_path_env(self, tmp_path, monkeypatch):
        env_archive = tmp_path / "env_archive"
        monkeypatch.setenv("ARCHIVE_PATH", str(env_archive))
        result = resolve_output_dir(None)
        assert result == str(env_archive)

    def test_creates_directory_if_missing(self, tmp_path):
        """This is the case that actually surfaced during manual testing:
        `download ytdl` against a brand-new output path."""
        target = tmp_path / "brand" / "new" / "path"
        assert not target.exists()
        result = resolve_output_dir(str(target))
        assert os.path.isdir(result)

    def test_existing_directory_is_left_alone(self, tmp_path):
        target = tmp_path / "already_here"
        target.mkdir()
        (target / "existing_file.txt").write_text("keep me")
        resolve_output_dir(str(target))
        assert (target / "existing_file.txt").exists()


class TestBuildLibraryIndex:
    def test_indexes_audio_extensions_only(self, tmp_path):
        (tmp_path / "song.mp3").write_text("x")
        (tmp_path / "notes.txt").write_text("x")
        index = build_library_index(str(tmp_path))
        assert len(index) == 1

    def test_skips_pycache_directories(self, tmp_path):
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "song.mp3").write_text("x")
        (tmp_path / "real_song.mp3").write_text("x")
        index = build_library_index(str(tmp_path))
        assert len(index) == 1

    def test_missing_root_returns_empty_set(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        assert build_library_index(str(missing)) == set()

    def test_none_root_returns_empty_set(self):
        assert build_library_index(None) == set()

    def test_recurses_into_subdirectories(self, tmp_path):
        nested = tmp_path / "albums" / "Artist" / "Album"
        nested.mkdir(parents=True)
        (nested / "track.mp3").write_text("x")
        index = build_library_index(str(tmp_path))
        assert len(index) == 1


class TestScanExistingFuzzy:
    def test_normalizes_before_comparing(self):
        # library index built from a differently-cased/punctuated stem
        library_index = {"testartisttesttrack"}
        existing, new = scan_existing_fuzzy(["Test Artist - Test Track.mp3"], library_index)
        assert (existing, new) == (1, 0)

    def test_counts_genuinely_new_files(self):
        library_index = {"somethingelse"}
        existing, new = scan_existing_fuzzy(["Brand New Track.mp3"], library_index)
        assert (existing, new) == (0, 1)

    def test_mixed_batch(self):
        library_index = {"testartisttesttrack"}
        candidates = ["Test Artist - Test Track.mp3", "New Artist - New Track.mp3"]
        existing, new = scan_existing_fuzzy(candidates, library_index)
        assert (existing, new) == (1, 1)
