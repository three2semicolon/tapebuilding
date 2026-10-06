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
    check_tags,
    group_files,
    is_unrelated_va_collision,
    prune_empty_dirs,
    resolve_crate,
    run_cleanup,
)
from lib.tags import read_tags, scan_audio


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
        plan = build_plan(groups, str(crate))

        # With Bug 2b fix, disjoint artist groups should be split apart
        # Expect 3 singleton moves, no VA group
        assert len(plan.va_groups) == 0
        assert len(plan.singleton_moves) == 3

    def test_shared_majority_artist_does_not_get_filed_as_various(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01.mp3",
                          artist="Nova", album="Nightfall", title="One", track=1)
        make_tagged_file(filename="crate/albums/Nova - Nightfall/02.mp3",
                          artist="Nova & Guest", album="Nightfall", title="Two", track=2)
        crate = tmp_path / "crate"

        files = scan_audio(str(crate))
        groups = group_files(files)
        plan = build_plan(groups, str(crate))

        assert plan.va_groups == []


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
        plan = build_plan(groups, str(crate))

        assert len(plan.tag_writes) == 1
        path, aa = plan.tag_writes[0]
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
        # With Bug 2b fix, disjoint artist groups are split apart, so no VA albums reported
        assert "'Various Artists' albums  : 0" in out
        assert "Comp" in out  # Album name still appears in context of singleton processing

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
        # resolve_crate() moved into organize.cleanup.common when cleanup.py
        # was split into a subpackage - patch resolve_path there, not on the
        # organize.cleanup package itself. organize.cleanup only re-exports
        # resolve_crate (see its __init__.py); setattr-ing "resolve_path" on
        # the package module wouldn't touch the name resolve_crate() actually
        # looks up, which lives in common.py's own module namespace.
        import organize.cleanup.common as common_module

        def _raise(*a, **kw):
            raise ValueError("ARCHIVE_PATH is required")
        monkeypatch.setattr(common_module, "resolve_path", _raise)

        with pytest.raises(ValueError):
            resolve_crate()

    def test_explicit_crate_arg_is_returned(self, tmp_path):
        assert resolve_crate(str(tmp_path)) == str(tmp_path)


class TestIsUnrelatedVaCollision:
    """Tests for the broadened is_unrelated_va_collision() - Bug 2 fix.

    The real condition: exactly 2 tracks with completely disjoint
    normalized artist tokens (artist + albumartist union), and neither
    track's own albumartist tag explicitly says Various Artists/VA.
    This catches both the 'Various Artists' fallback case AND the tie-break
    case (e.g. Diversa's "Ego Death" and The Internet's "Ego Death"
    landing in the same group — canonical_albumartist picks one artist
    on a 50% tie, but the tracks are unrelated).
    """

    def test_disjoint_artists_two_tracks_returns_true(self, tmp_path, make_tagged_file):
        """Two tracks with completely disjoint artist tokens -> collision detected."""
        # Track 1: artist=Diversa, no albumartist -> tokens={'diversa'}
        # Track 2: artist=The Internet, albumartist=The Internet -> tokens={'theinternet'}
        # Disjoint -> should return True
        f1 = {"artist": "Diversa", "albumartist": "", "album": "Ego Death", "title": "Ego Death"}
        f2 = {"artist": "The Internet", "albumartist": "The Internet", "album": "Ego Death", "title": "Ego Death"}
        assert is_unrelated_va_collision([f1, f2]) is True

    def test_disjoint_artists_with_canonical_aa_not_va_returns_true(self, tmp_path, make_tagged_file):
        """Same as above but canonical_albumartist would pick one artist (not VA) - still collision."""
        # This is the exact Diversa/Internet case: canonical_albumartist returns "The Internet"
        # on a 50% tie, but they're unrelated singles sharing a title
        f1 = {"artist": "Diversa", "albumartist": "", "album": "Ego Death", "title": "Ego Death"}
        f2 = {"artist": "The Internet", "albumartist": "The Internet", "album": "Ego Death", "title": "Ego Death"}
        assert is_unrelated_va_collision([f1, f2]) is True

    def test_shared_artist_token_returns_false(self, tmp_path, make_tagged_file):
        """Two tracks sharing an artist token -> not a collision (real album/collab)."""
        # Track 1: artist="Nova", Track 2: artist="Nova & Guest"
        # Share 'nova' token -> should return False
        f1 = {"artist": "Nova", "albumartist": "", "album": "Nightfall", "title": "One"}
        f2 = {"artist": "Nova & Guest", "albumartist": "", "album": "Nightfall", "title": "Two"}
        assert is_unrelated_va_collision([f1, f2]) is False

    def test_explicit_va_albumartist_returns_false(self, tmp_path, make_tagged_file):
        """If either track has explicit Various Artists albumartist -> trust it, not a collision."""
        f1 = {"artist": "Alpha", "albumartist": "Various Artists", "album": "Comp", "title": "One"}
        f2 = {"artist": "Beta", "albumartist": "", "album": "Comp", "title": "Two"}
        assert is_unrelated_va_collision([f1, f2]) is False

    def test_three_tracks_returns_false(self, tmp_path, make_tagged_file):
        """Three tracks with disjoint artists -> not auto-split (left to ambiguous VA path)."""
        f1 = {"artist": "A", "albumartist": "", "album": "X", "title": "One"}
        f2 = {"artist": "B", "albumartist": "", "album": "X", "title": "Two"}
        f3 = {"artist": "C", "albumartist": "", "album": "X", "title": "Three"}
        assert is_unrelated_va_collision([f1, f2, f3]) is False

    def test_single_track_returns_false(self, tmp_path, make_tagged_file):
        """Single track -> not a collision."""
        f1 = {"artist": "A", "albumartist": "", "album": "X", "title": "One"}
        assert is_unrelated_va_collision([f1]) is False


class TestCheckTags:
    """Tests for check_tags() - scan/fix corrupted albumartist tags."""

    def test_detects_corrupted_singles_albumartist(self, tmp_path, make_tagged_file):
        """Singles with non-empty albumartist (not VA, not own artist, not label, not collab) -> flagged."""
        # Diversa in singles/ with albumartist="The Internet" from past wrong merge
        make_tagged_file(filename="crate/singles/Diversa - Ego Death.mp3",
                          artist="Diversa", albumartist="The Internet", album="Ego Death",
                          title="Ego Death")
        # Normal single with no albumartist -> flagged as missing (should be set to artist)
        make_tagged_file(filename="crate/singles/Other - Song.mp3",
                          artist="Other", albumartist="", album="", title="Song")
        # Single with explicit VA -> not flagged
        make_tagged_file(filename="crate/singles/Comp - Track.mp3",
                          artist="Comp", albumartist="Various Artists", album="Comp",
                          title="Track")
        crate = tmp_path / "crate"

        result = check_tags(crate=str(crate), apply=False)

        # Now flags 2: Diversa (corruption) + Other (missing)
        assert result['suspicious'] == 2
        assert result['fixed'] == 0

    def test_apply_sets_corrupted_singles_albumartist_to_artist(self, tmp_path, make_tagged_file):
        """With --apply, sets corrupted albumartist to the track's own artist (not clear)."""
        make_tagged_file(filename="crate/singles/Diversa - Ego Death.mp3",
                          artist="Diversa", albumartist="The Internet", album="Ego Death",
                          title="Ego Death")
        crate = tmp_path / "crate"

        result = check_tags(crate=str(crate), apply=True)

        assert result['suspicious'] == 1
        assert result['fixed'] == 1
        # Verify the tag was SET to artist, not cleared
        tags = read_tags(str(crate / "singles" / "Diversa - Ego Death.mp3"))
        assert tags['albumartist'] == 'Diversa'

    def test_skips_collaboration_albumartist(self, tmp_path, make_tagged_file):
        """Collaboration: artist='Skrillex & Fred again..', albumartist='Skrillex' -> not flagged."""
        make_tagged_file(filename="crate/singles/Skrillex_Fred again.. - Rumble.mp3",
                          artist="Skrillex & Fred again..", albumartist="Skrillex", album="Rumble",
                          title="Rumble")
        crate = tmp_path / "crate"

        result = check_tags(crate=str(crate), apply=False)
        assert result['suspicious'] == 0

    def test_skips_label_albumartist(self, tmp_path, make_tagged_file):
        """Known label albumartist (Monstercat) -> not flagged."""
        make_tagged_file(filename="crate/singles/Rundfunk - Turn Around.mp3",
                          artist="Rundfunk", albumartist="Monstercat", album="Monstercat 030",
                          title="Turn Around")
        crate = tmp_path / "crate"

        result = check_tags(crate=str(crate), apply=False)
        assert result['suspicious'] == 0

    def test_apply_sets_missing_albumartist_to_artist(self, tmp_path, make_tagged_file):
        """With --apply, missing albumartist gets set to the track's artist."""
        make_tagged_file(filename="crate/singles/Other - Song.mp3",
                          artist="Other", albumartist="", album="", title="Song")
        crate = tmp_path / "crate"

        result = check_tags(crate=str(crate), apply=True)

        assert result['suspicious'] == 1
        assert result['fixed'] == 1
        tags = read_tags(str(crate / "singles" / "Other - Song.mp3"))
        assert tags['albumartist'] == 'Other'

    def test_detects_albums_albumartist_mismatch(self, tmp_path, make_tagged_file):
        """Album files whose albumartist disagrees with folder canonical -> flagged."""
        # Folder canonical would be "Nova" but one file has "Wrong Artist"
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01 One.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall",
                          title="One", track=1)
        make_tagged_file(filename="crate/albums/Nova - Nightfall/02 Two.mp3",
                          artist="Nova", albumartist="Wrong Artist", album="Nightfall",
                          title="Two", track=2)
        crate = tmp_path / "crate"

        result = check_tags(crate=str(crate), apply=False)

        assert result['suspicious'] == 1
        assert result['fixed'] == 0

    def test_apply_fixes_albums_albumartist_mismatch(self, tmp_path, make_tagged_file):
        """With --apply, corrects the albumartist to canonical value."""
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01 One.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall",
                          title="One", track=1)
        make_tagged_file(filename="crate/albums/Nova - Nightfall/02 Two.mp3",
                          artist="Nova", albumartist="Wrong Artist", album="Nightfall",
                          title="Two", track=2)
        crate = tmp_path / "crate"

        result = check_tags(crate=str(crate), apply=True)

        assert result['suspicious'] == 1
        assert result['fixed'] == 1
        # Verify the tag was corrected
        tags = read_tags(str(crate / "albums" / "Nova - Nightfall" / "02 Two.mp3"))
        assert tags['albumartist'] == 'Nova'

    def test_no_anomalies_returns_zero(self, tmp_path, make_tagged_file):
        """Clean crate -> no suspicious files."""
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01 One.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall",
                          title="One", track=1)
        make_tagged_file(filename="crate/singles/Other - Song.mp3",
                          artist="Other", albumartist="Other", album="", title="Song")
        crate = tmp_path / "crate"

        result = check_tags(crate=str(crate), apply=False)

        assert result['suspicious'] == 0
        assert result['fixed'] == 0


