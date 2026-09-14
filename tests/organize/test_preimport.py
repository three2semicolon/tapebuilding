"""Tests for organize.preimport - TEST_PLANS.md 'organize/preimport.py'
section.

Written against the actual current source. Uses make_tagged_file (see
tests/organize/conftest.py) to build real crate/unorganized fixtures on
disk - stage()'s merge/stage/singleton/ambiguous decisions are all driven
by real mediafile tags read back off disk (canonical_albumartist(),
dominant_album(), normalize_key()), so a hand-rolled fake tag dict
wouldn't exercise the actual decision path the way it matters here.
"""
import os

import pytest

from organize.preimport import stage, index_existing_albums
from lib.tags import read_tags
from lib.text import normalize_key


class TestStageNewFolder:
    def test_creates_staged_folder_for_multi_track_album_with_no_existing_match(
        self, tmp_path, make_tagged_file
    ):
        make_tagged_file(filename="unorganized/01 One.mp3", artist="Nova",
                          album="Nightfall", title="One", track=1)
        make_tagged_file(filename="unorganized/02 Two.mp3", artist="Nova",
                          album="Nightfall", title="Two", track=2)
        crate = tmp_path / "crate"

        report = stage(str(tmp_path / "unorganized"), str(crate), apply=True)

        assert len(report['staged_folders']) == 1
        staged = report['staged_folders'][0]
        assert os.path.basename(staged) == "Nova - Nightfall"
        assert set(os.listdir(staged)) == {"01 - Nova - One.mp3", "02 - Nova - Two.mp3"}

    def test_writes_canonical_albumartist_tag_onto_staged_files(self, tmp_path, make_tagged_file):
        # neither file carries an albumartist tag - stage() should write
        # the canonical one (derived from the shared artist) into both.
        make_tagged_file(filename="unorganized/01 One.mp3", artist="Nova",
                          album="Nightfall", title="One", track=1)
        make_tagged_file(filename="unorganized/02 Two.mp3", artist="Nova",
                          album="Nightfall", title="Two", track=2)
        crate = tmp_path / "crate"

        report = stage(str(tmp_path / "unorganized"), str(crate), apply=True)

        staged = report['staged_folders'][0]
        for fn in os.listdir(staged):
            assert read_tags(os.path.join(staged, fn))['albumartist'] == 'Nova'


class TestStageMergeExisting:
    def test_merges_into_existing_crate_album_folder(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01 - Nova - One.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall",
                          title="One", track=1)
        make_tagged_file(filename="unorganized/02 Two.mp3", artist="Nova",
                          album="Nightfall", title="Two", track=2)
        make_tagged_file(filename="unorganized/03 Three.mp3", artist="Nova",
                          album="Nightfall", title="Three", track=3)
        crate = tmp_path / "crate"

        report = stage(str(tmp_path / "unorganized"), str(crate), apply=True)

        existing_folder = str(crate / "albums" / "Nova - Nightfall")
        assert report['merged_folders'] == [existing_folder]
        assert report['merged_tracks'] == 2
        assert report['staged_folders'] == []
        assert set(os.listdir(existing_folder)) == {
            "01 - Nova - One.mp3", "02 - Nova - Two.mp3", "03 - Nova - Three.mp3",
        }

    def test_merge_writes_the_existing_folders_albumartist_not_the_incoming_ones(
        self, tmp_path, make_tagged_file
    ):
        # crate folder's canonical tag is "The Band"; the incoming track's
        # own artist tag is differently-cased - aa_for_tag should still
        # come from the existing folder, not be recomputed from the
        # incoming group alone.
        make_tagged_file(filename="crate/albums/The Band - Nightfall/01.mp3",
                          artist="The Band", albumartist="The Band",
                          album="Nightfall", title="One", track=1)
        make_tagged_file(filename="unorganized/02 Two.mp3", artist="the band",
                          album="Nightfall", title="Two", track=2)
        crate = tmp_path / "crate"

        stage(str(tmp_path / "unorganized"), str(crate), apply=True)

        merged_path = os.path.join(str(crate / "albums" / "The Band - Nightfall"),
                                    "02 - the band - Two.mp3")
        assert os.path.exists(merged_path)
        assert read_tags(merged_path)['albumartist'] == 'The Band'

    def test_track_already_present_in_target_album_is_quarantined_not_duplicated(
        self, tmp_path, make_tagged_file
    ):
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01 - Nova - One.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall",
                          title="One", track=1)
        dup_incoming = make_tagged_file(filename="unorganized/01 One (dup).mp3",
                                         artist="Nova", album="Nightfall",
                                         title="One", track=1)
        make_tagged_file(filename="unorganized/02 Two.mp3", artist="Nova",
                          album="Nightfall", title="Two", track=2)
        crate = tmp_path / "crate"

        report = stage(str(tmp_path / "unorganized"), str(crate), apply=True)

        assert len(report['duplicates']) == 1
        assert report['duplicates'][0][2] == "One"
        quarantined = os.path.join(str(crate / "duplicates"), os.path.basename(dup_incoming))
        assert os.path.exists(quarantined)
        # the genuinely new track still merges normally
        assert os.path.exists(
            os.path.join(str(crate / "albums" / "Nova - Nightfall"), "02 - Nova - Two.mp3")
        )

    def test_no_merge_existing_stages_a_new_folder_even_with_a_matching_existing_album(
        self, tmp_path, make_tagged_file
    ):
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01 - Nova - One.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall",
                          title="One", track=1)
        make_tagged_file(filename="unorganized/02 Two.mp3", artist="Nova",
                          album="Nightfall", title="Two", track=2)
        make_tagged_file(filename="unorganized/03 Three.mp3", artist="Nova",
                          album="Nightfall", title="Three", track=3)
        crate = tmp_path / "crate"

        report = stage(str(tmp_path / "unorganized"), str(crate), apply=True,
                        merge_existing=False)

        assert report['merged_folders'] == []
        assert report['merged_tracks'] == 0
        assert len(report['staged_folders']) == 1


class TestStageSingletonPassthrough:
    def test_track_with_no_album_tag_stays_in_place(self, tmp_path, make_tagged_file):
        loose_path = make_tagged_file(filename="unorganized/Loose Song.mp3",
                                       artist="Solo", title="Loose Song")
        crate = tmp_path / "crate"

        report = stage(str(tmp_path / "unorganized"), str(crate), apply=True)

        assert report['singletons'] == 1
        assert os.path.exists(loose_path)
        assert report['staged_folders'] == []
        assert report['merged_folders'] == []

    def test_lone_track_of_an_unmatched_album_behaves_like_a_singleton(
        self, tmp_path, make_tagged_file
    ):
        # has an album tag, but it's the only track under that album and
        # nothing in the crate matches it - build_plan's 'pass' outcome.
        loose_path = make_tagged_file(filename="unorganized/Track.mp3", artist="Solo",
                                       album="Rare EP", title="Track", track=1)
        crate = tmp_path / "crate"

        report = stage(str(tmp_path / "unorganized"), str(crate), apply=True)

        assert report['singletons'] == 1
        assert os.path.exists(loose_path)


class TestIndexExistingAlbumsAmbiguity:
    def test_two_folders_normalizing_to_the_same_key_are_flagged_ambiguous(
        self, tmp_path, make_tagged_file
    ):
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall",
                          title="One", track=1)
        # a second, distinct folder whose tags normalize to the SAME key
        # (case/punctuation differences only) - a real accidental duplicate.
        make_tagged_file(filename="crate/albums/nova - nightfall!/01.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall!",
                          title="One", track=1)

        idx = index_existing_albums(str(tmp_path / "crate"))
        key = (normalize_key("Nova"), normalize_key("Nightfall"))
        assert idx[key] is None

    def test_ambiguous_key_refuses_merge_and_stages_new_folder_instead(
        self, tmp_path, make_tagged_file
    ):
        make_tagged_file(filename="crate/albums/Nova - Nightfall/01.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall",
                          title="One", track=1)
        make_tagged_file(filename="crate/albums/nova - nightfall!/01.mp3",
                          artist="Nova", albumartist="Nova", album="Nightfall!",
                          title="One", track=1)
        make_tagged_file(filename="unorganized/02 Two.mp3", artist="Nova",
                          album="Nightfall", title="Two", track=2)
        make_tagged_file(filename="unorganized/03 Three.mp3", artist="Nova",
                          album="Nightfall", title="Three", track=3)
        crate = tmp_path / "crate"

        report = stage(str(tmp_path / "unorganized"), str(crate), apply=True)

        assert report['merged_folders'] == []  # refused, not silently merged
        assert len(report['staged_folders']) == 1  # staged as a new folder instead
        assert report['ambiguous'] == [("Nova", "Nightfall")]


class TestStageReportShape:
    def test_report_dict_has_expected_keys(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="unorganized/loose.mp3", artist="Solo", title="Loose")
        crate = tmp_path / "crate"

        report = stage(str(tmp_path / "unorganized"), str(crate), apply=False)

        assert set(report.keys()) == {
            'scanned', 'staged_folders', 'merged_folders', 'merged_tracks',
            'duplicates', 'tag_writes', 'singletons', 'ambiguous',
        }

    def test_missing_input_dir_returns_a_report_without_erroring(self, tmp_path):
        report = stage(str(tmp_path / "does_not_exist"), str(tmp_path / "crate"))
        assert report == {
            'staged_folders': [], 'merged_folders': [], 'merged_tracks': 0,
            'singletons': 0, 'tag_writes': 0, 'ambiguous': [], 'scanned': 0,
        }

    def test_missing_input_dir_report_omits_duplicates_key_unlike_the_normal_path(self, tmp_path):
        """Not a claim this is correct - the early 'input dir not found'
        return literal in stage() has a different key set than the normal
        end-of-function report dict (no 'duplicates' key). A caller that
        reads report['duplicates'] unconditionally (organize.preimport's
        own printing does exactly this further down) would KeyError on a
        missing-input call. Pinned as current behavior; see TODO.md."""
        report = stage(str(tmp_path / "does_not_exist"), str(tmp_path / "crate"))
        assert 'duplicates' not in report


class TestStageDryRun:
    def test_dry_run_does_not_move_files_or_write_tags(self, tmp_path, make_tagged_file):
        p1 = make_tagged_file(filename="unorganized/01 One.mp3", artist="Nova",
                               album="Nightfall", title="One", track=1)
        p2 = make_tagged_file(filename="unorganized/02 Two.mp3", artist="Nova",
                               album="Nightfall", title="Two", track=2)
        crate = tmp_path / "crate"

        report = stage(str(tmp_path / "unorganized"), str(crate), apply=False)

        assert len(report['staged_folders']) == 1  # planned...
        assert not os.path.isdir(report['staged_folders'][0])  # ...but not created
        assert os.path.exists(p1) and os.path.exists(p2)
        assert read_tags(p1)['albumartist'] == ''  # tag left untouched
