"""Tests for organize.cleanup - TEST_PLANS.md 'organize/cleanup.py'
section.

Written against the actual current source. Like test_preimport.py, uses
make_tagged_file (see tests/organize/conftest.py) to build real crate
fixtures on disk - group_files()/build_plan()/run_cleanup() all operate on
dicts read straight off file tags via lib.tags.scan_audio(), and run_cleanup()
itself calls lib.tags.canonical_albumartist()/dominant_album()/sanitize()/
safe_move()/write_tag(), so a hand-rolled fake tag dict wouldn't exercise the
actual regrouping decisions the way it matters here.
"""
import os

import pytest

from organize.cleanup import (
    build_plan,
    group_files,
    prune_empty_dirs,
    resolve_crate,
    run_cleanup,
)
from lib.tags import scan_audio


class TestGroupFiles:
    def test_same_normalized_album_groups_together(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall",
                          title="One", track=1)
        make_tagged_file(filename="crate/albums/Nova - Nightfall/02.mp3",
                          artist="Nova", albumartist="Nova", album="NIGHTFALL",
                          title="Two", track=2)
        crate = tmp_path / "crate"

        files = scan_audio(str(crate))
        groups = group_files(files)

        album_groups = [m for k, m in groups.items() if k[0] == 'album']
        assert len(album_groups) == 1
        assert len(album_groups[0]) == 2

    def test_files_with_no_album_tag_never_merge_with_each_other(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="crate/singles/Loose.mp3", artist="Solo", title="Loose")
        make_tagged_file(filename="crate/singles/Loose2.mp3", artist="Solo", title="Loose2")
        crate = tmp_path / "crate"

        files = scan_audio(str(crate))
        groups = group_files(files)

        single_keys = [k for k in groups if k[0] == 'single']
        assert len(single_keys) == 2
        assert all(len(groups[k]) == 1 for k in single_keys)


class TestBuildPlanVariousArtists:
    def test_no_majority_artist_files_under_various_artists(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="crate/albums/mix/01.mp3", artist="Alpha",
                          album="Comp", title="One", track=1)
        make_tagged_file(filename="crate/albums/mix/02.mp3", artist="Beta",
                          album="Comp", title="Two", track=2)
        make_tagged_file(filename="crate/albums/mix/03.mp3", artist="Gamma",
                          album="Comp", title="Three", track=3)
        crate = tmp_path / "crate"

        files = scan_audio(str(crate))
        groups = group_files(files)
        _, _, _, _, va_groups = build_plan(groups, str(crate))

        assert len(va_groups) == 1
        album, count, _src_folders = va_groups[0]
        assert album == "Comp"
        assert count == 3

    def test_shared_majority_artist_does_not_get_filed_as_various(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01.mp3",
                          artist="Nova", album="Nightfall", title="One", track=1)
        make_tagged_file(filename="crate/albums/Nova - Nightfall/02.mp3",
                          artist="Nova & Guest", album="Nightfall", title="Two", track=2)
        crate = tmp_path / "crate"

        files = scan_audio(str(crate))
        groups = group_files(files)
        _, _, _, _, va_groups = build_plan(groups, str(crate))

        assert va_groups == []


class TestBuildPlanTagWrites:
    def test_writes_canonical_albumartist_only_when_it_differs_from_existing_tag(
        self, tmp_path, make_tagged_file
    ):
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall",
                          title="One", track=1)
        # no albumartist tag on this one - should need a tag write
        make_tagged_file(filename="crate/albums/Nova - Nightfall/02.mp3",
                          artist="Nova", album="Nightfall", title="Two", track=2)
        crate = tmp_path / "crate"

        files = scan_audio(str(crate))
        groups = group_files(files)
        _, _, _, tag_writes, _ = build_plan(groups, str(crate))

        assert len(tag_writes) == 1
        path, aa = tag_writes[0]
        assert aa == "Nova"
        assert path.endswith("02.mp3")


class TestRunCleanupSummaryFlags:
    def test_flags_va_filed_albums_in_dry_run_summary(self, tmp_path, make_tagged_file, capsys):
        make_tagged_file(filename="crate/albums/mix/01.mp3", artist="Alpha",
                          album="Comp", title="One", track=1)
        make_tagged_file(filename="crate/albums/mix/02.mp3", artist="Beta",
                          album="Comp", title="Two", track=2)
        make_tagged_file(filename="crate/albums/mix/03.mp3", artist="Gamma",
                          album="Comp", title="Three", track=3)
        crate = tmp_path / "crate"

        run_cleanup(crate=str(crate), apply=False)

        out = capsys.readouterr().out
        assert "'Various Artists' albums  : 1" in out
        assert "Comp" in out

    def test_flags_unusually_large_album_group_as_plausible_wrong_merge(
        self, tmp_path, make_tagged_file, capsys
    ):
        for i in range(1, 6):
            make_tagged_file(filename=f"crate/albums/Nova - Big/{i:02d}.mp3",
                              artist="Nova", albumartist="Nova", album="Big",
                              title=f"Track {i}", track=i)
        make_tagged_file(filename="crate/albums/Nova - Small/01.mp3",
                          artist="Nova", albumartist="Nova", album="Small",
                          title="One", track=1)
        make_tagged_file(filename="crate/albums/Nova - Small/02.mp3",
                          artist="Nova", albumartist="Nova", album="Small",
                          title="Two", track=2)
        crate = tmp_path / "crate"

        run_cleanup(crate=str(crate), apply=False)

        out = capsys.readouterr().out
        assert "largest album groups" in out
        assert "'Big'" in out


class TestRunCleanupIdempotent:
    def test_second_apply_run_moves_and_writes_nothing(self, tmp_path, make_tagged_file, capsys):
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01 One.mp3",
                          artist="Nova", album="Nightfall", title="One", track=1)
        make_tagged_file(filename="crate/albums/Nova - Nightfall/02 Two.mp3",
                          artist="Nova", album="Nightfall", title="Two", track=2)
        crate = tmp_path / "crate"

        run_cleanup(crate=str(crate), apply=True)
        capsys.readouterr()  # discard first-run output (it does the renaming)

        run_cleanup(crate=str(crate), apply=True)
        out = capsys.readouterr().out

        assert "files moving to albums/   : 0" in out
        assert "files moving to singles/  : 0" in out
        assert "albumartist tags to write : 0" in out


class TestPruneEmptyDirs:
    def test_removes_now_empty_album_folders_but_keeps_root(self, tmp_path):
        crate = tmp_path / "crate"
        empty_album = crate / "albums" / "Empty Folder"
        empty_album.mkdir(parents=True)

        prune_empty_dirs(str(crate))

        assert not empty_album.exists()
        assert (crate / "albums").exists()


class TestResolveCrateRequiredNoFallback:
    """Same strictness family as organize.beets_import.run_import()'s
    ARCHIVE_PATH handling - both move files on disk, both should raise
    rather than guess a directory."""

    def test_raises_when_no_crate_arg_and_archive_path_unresolved(self, monkeypatch):
        import organize.cleanup as cleanup_module

        def _raise(*a, **kw):
            raise ValueError("ARCHIVE_PATH is required")
        monkeypatch.setattr(cleanup_module, "resolve_path", _raise)

        with pytest.raises(ValueError):
            resolve_crate()

    def test_explicit_crate_arg_is_returned(self, tmp_path):
        assert resolve_crate(str(tmp_path)) == str(tmp_path)
