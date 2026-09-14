"""Tests for organize.beets_import - TEST_PLANS.md
'organize/beets_import.py' section.

Written against the actual current source. beets itself is never invoked -
every subprocess.run() call is faked at the organize.beets_import module
level, and organize.preimport.stage() is faked too, since this file's job
is to pin beets_import's own orchestration and target-selection logic
(_album_pass_target, the ARCHIVE_PATH strictness, the automatic-preimport
wiring), not preimport's or beets' actual behavior - preimport gets its
own real, on-disk coverage in test_preimport.py.
"""
import os
from types import SimpleNamespace

import pytest

import organize.beets_import as beets_import
import organize.preimport as preimport_module


# --- _resolve_albums_input -------------------------------------------------

class TestResolveAlbumsInput:
    def test_prefers_albums_subdir_when_present(self, tmp_path):
        (tmp_path / "albums").mkdir()
        assert beets_import._resolve_albums_input(str(tmp_path)) == str(tmp_path / "albums")

    def test_falls_back_to_input_dir_when_no_albums_subdir(self, tmp_path):
        assert beets_import._resolve_albums_input(str(tmp_path)) == str(tmp_path)


# --- _album_pass_target -----------------------------------------------------

class TestAlbumPassTarget:
    def test_targets_only_staged_albums_dir_when_preimport_staged_something(self, tmp_path):
        input_dir = str(tmp_path / "unorganized")
        target = beets_import._album_pass_target(
            input_dir, preimport_ran=True,
            staged_folders=[os.path.join(input_dir, "albums", "Nova - Nightfall")],
        )
        assert target == os.path.join(input_dir, "albums")

    def test_skipped_entirely_when_nothing_staged(self, tmp_path):
        """PACKAGE_OVERVIEW.md calls this out as a fixed pre-refactor bug -
        the album pass must never fall through to a flat directory of loose
        singletons (which beets would group as one bogus multi-track album).
        Regression test per TEST_PLANS.md."""
        input_dir = str(tmp_path / "unorganized")
        target = beets_import._album_pass_target(input_dir, preimport_ran=True, staged_folders=[])
        assert target is None

    def test_falls_back_to_legacy_resolution_when_preimport_did_not_run(self, tmp_path):
        input_dir = tmp_path / "unorganized"
        (input_dir / "albums").mkdir(parents=True)
        target = beets_import._album_pass_target(str(input_dir), preimport_ran=False, staged_folders=[])
        assert target == str(input_dir / "albums")

    def test_legacy_resolution_falls_back_to_input_dir_when_no_albums_subdir(self, tmp_path):
        input_dir = tmp_path / "unorganized"
        input_dir.mkdir()
        target = beets_import._album_pass_target(str(input_dir), preimport_ran=False, staged_folders=[])
        assert target == str(input_dir)


# --- _warn_singles_after_albums ---------------------------------------------

class TestWarnSinglesAfterAlbums:
    def test_no_warning_when_no_albums_subdir(self, tmp_path, capsys):
        beets_import._warn_singles_after_albums(str(tmp_path))
        assert capsys.readouterr().out == ""

    def test_no_warning_when_albums_subdir_has_no_audio(self, tmp_path, capsys):
        (tmp_path / "albums").mkdir()
        (tmp_path / "albums" / "cover.jpg").write_text("x")
        beets_import._warn_singles_after_albums(str(tmp_path))
        assert capsys.readouterr().out == ""

    def test_warns_when_albums_subdir_still_has_audio(self, tmp_path, capsys):
        album_dir = tmp_path / "albums" / "Nova - Nightfall"
        album_dir.mkdir(parents=True)
        (album_dir / "01.mp3").write_bytes(b"")
        beets_import._warn_singles_after_albums(str(tmp_path))
        out = capsys.readouterr().out
        assert "warning" in out
        assert "singles pass" in out


# --- run_import(): ARCHIVE_PATH required, no fallback -----------------------

class TestRunImportArchivePathRequired:
    """Same strictness family as organize.cleanup.resolve_crate() - both
    move files on disk, both should raise rather than guess a directory."""

    def test_raises_when_no_output_dir_and_archive_path_unresolved(self, tmp_path, monkeypatch):
        def _raise(*a, **kw):
            raise ValueError("ARCHIVE_PATH is required")
        monkeypatch.setattr(beets_import, "resolve_path", _raise)

        with pytest.raises(ValueError):
            beets_import.run_import(str(tmp_path / "unorganized"))

    def test_explicit_output_dir_bypasses_archive_path_resolution(self, tmp_path, monkeypatch):
        def _fail(*a, **kw):
            raise AssertionError("resolve_path should not be called when output_dir is given")
        monkeypatch.setattr(beets_import, "resolve_path", _fail)

        # input dir doesn't exist -> run_import should fail there, proving it
        # got past output_dir resolution without calling resolve_path at all.
        ok = beets_import.run_import(str(tmp_path / "does_not_exist"),
                                      output_dir=str(tmp_path / "out"))
        assert ok is False


# --- run_import(): automatic preimport wiring -------------------------------

class TestRunImportPreimportAutomatic:
    def _patch_passes(self, monkeypatch):
        calls = {"album": [], "singles": []}
        monkeypatch.setattr(
            beets_import, "run_album_pass",
            lambda target, output_dir, dry_run, timid: calls["album"].append(target) or True,
        )
        monkeypatch.setattr(
            beets_import, "run_singles_pass",
            lambda input_dir, output_dir, dry_run: calls["singles"].append(input_dir) or True,
        )
        monkeypatch.setattr(beets_import, "print_library_stats", lambda *a, **kw: None)
        monkeypatch.setattr(beets_import, "export_library_csv", lambda *a, **kw: None)
        return calls

    def test_preimport_runs_by_default(self, tmp_path, monkeypatch):
        input_dir = tmp_path / "unorganized"
        input_dir.mkdir()
        output_dir = tmp_path / "crate"
        output_dir.mkdir()
        self._patch_passes(monkeypatch)

        seen = {}
        def fake_stage(inp, outp, apply, merge_existing, verbose):
            seen["args"] = (inp, outp)
            return {"merged_folders": [], "staged_folders": []}
        monkeypatch.setattr(preimport_module, "stage", fake_stage)

        beets_import.run_import(str(input_dir), output_dir=str(output_dir))

        assert seen["args"] == (str(input_dir), str(output_dir))

    def test_no_preimport_flag_skips_staging(self, tmp_path, monkeypatch):
        input_dir = tmp_path / "unorganized"
        input_dir.mkdir()
        output_dir = tmp_path / "crate"
        output_dir.mkdir()
        self._patch_passes(monkeypatch)

        def fail_stage(*a, **kw):
            raise AssertionError("stage() should not be called with no_preimport=True")
        monkeypatch.setattr(preimport_module, "stage", fail_stage)

        beets_import.run_import(str(input_dir), output_dir=str(output_dir), no_preimport=True)
        # getting here without the AssertionError is the assertion

    def test_singles_only_pass_skips_preimport(self, tmp_path, monkeypatch):
        input_dir = tmp_path / "unorganized"
        input_dir.mkdir()
        output_dir = tmp_path / "crate"
        output_dir.mkdir()
        self._patch_passes(monkeypatch)

        def fail_stage(*a, **kw):
            raise AssertionError("stage() should not run for a singles-only pass")
        monkeypatch.setattr(preimport_module, "stage", fail_stage)

        beets_import.run_import(str(input_dir), output_dir=str(output_dir), only_pass="singles")

    def test_input_equal_to_output_skips_staging(self, tmp_path, monkeypatch, capsys):
        crate = tmp_path / "crate"
        crate.mkdir()
        self._patch_passes(monkeypatch)

        def fail_stage(*a, **kw):
            raise AssertionError("stage() should not run when input is the crate root")
        monkeypatch.setattr(preimport_module, "stage", fail_stage)

        beets_import.run_import(str(crate), output_dir=str(crate))
        assert "skipping staging" in capsys.readouterr().out


# --- album pass never falls through when nothing was staged -----------------

class TestAlbumPassSkippedWhenNothingStaged:
    def test_album_pass_never_falls_through_to_flat_directory(self, tmp_path, monkeypatch, capsys):
        """End-to-end version of TestAlbumPassTarget's unit test, run through
        run_import() itself: with nothing staged, run_album_pass must not be
        invoked at all - not even pointed at the flat input dir."""
        input_dir = tmp_path / "unorganized"
        input_dir.mkdir()
        output_dir = tmp_path / "crate"
        output_dir.mkdir()

        album_calls = []
        monkeypatch.setattr(beets_import, "run_album_pass",
                             lambda *a, **kw: album_calls.append(a) or True)
        monkeypatch.setattr(beets_import, "run_singles_pass", lambda *a, **kw: True)
        monkeypatch.setattr(beets_import, "print_library_stats", lambda *a, **kw: None)
        monkeypatch.setattr(beets_import, "export_library_csv", lambda *a, **kw: None)
        monkeypatch.setattr(preimport_module, "stage",
                             lambda *a, **kw: {"merged_folders": [], "staged_folders": []})

        beets_import.run_import(str(input_dir), output_dir=str(output_dir))

        assert album_calls == []
        assert "album pass skipped" in capsys.readouterr().out


# --- dry-run still calls beets, just with --pretend -------------------------

class TestDryRunUsesBeetsPretend:
    def test_dry_run_passes_pretend_flag_not_a_full_skip(self, tmp_path, monkeypatch):
        """dry-run should still invoke beets (with --pretend), not skip the
        subprocess call outright - that's the difference between an actual
        preview and doing nothing."""
        input_dir = tmp_path / "unorganized"
        input_dir.mkdir()
        output_dir = tmp_path / "crate"
        output_dir.mkdir()

        calls = []
        def fake_run(cmd, *a, **kw):
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(beets_import.subprocess, "run", fake_run)

        # only_pass="singles" skips preimport, so no need to fake stage() here
        beets_import.run_import(str(input_dir), output_dir=str(output_dir),
                                 dry_run=True, only_pass="singles")

        assert calls, "beets should still be invoked in dry-run mode"
        assert "--pretend" in calls[0]
        assert "--quiet" not in calls[0]
