"""Bug 2b: same-titled singles from different artists must not be merged into
a 'Various Artists' album, at any group size - including groups already
poisoned by an earlier wrong merge (albumartist='Various Artists')."""
import os

from lib.tags import scan_audio
from organize.cleanup.grouping import build_plan, group_files

VA = "Various Artists"


def _plan(tmp_path):
    crate = tmp_path / "crate"
    return build_plan(group_files(scan_audio(str(crate))), str(crate))


class TestSameTitledSinglesStaySeparate:
    def test_five_poisoned_singles_in_a_va_folder_split_to_singles(self, tmp_path, make_tagged_file):
        for i, a in enumerate(["alici", "Marshmello", "Miso", "sobenoyse", "WILLOW"], 1):
            make_tagged_file(filename=f"crate/albums/Various Artists - Alone/{i:02d} - {a} - Alone.mp3",
                             artist=a, albumartist=VA, album="Alone", title="Alone", track=1)
        plan = _plan(tmp_path)
        assert plan.album_moves == []
        assert len(plan.singleton_moves) == 5
        assert all(os.sep + "singles" + os.sep in d for _, d in plan.singleton_moves)
        assert [g[0] for g in plan.split_groups] == ["Alone"]
        assert plan.va_groups == []

    def test_clean_singles_in_singles_dir_stay_put(self, tmp_path, make_tagged_file):
        for a in ["Solange", "Tessa Violet", "Jennifer Paige"]:
            make_tagged_file(filename=f"crate/singles/{a} - Crush.mp3",
                             artist=a, albumartist=a, album="Crush", title="Crush", track=1)
        plan = _plan(tmp_path)
        assert plan.album_moves == [] and plan.singleton_moves == []
        assert plan.noop_count == 3

    def test_two_unrelated_same_titled_singles_not_merged(self, tmp_path, make_tagged_file):
        for a in ["Anysia Kym", "Spencer."]:
            make_tagged_file(filename=f"crate/singles/{a} - Automatic.mp3",
                             artist=a, albumartist=a, album="Automatic", title="Automatic", track=1)
        assert _plan(tmp_path).album_moves == []

    def test_unrelated_singles_with_mixed_titles_all_separate(self, tmp_path, make_tagged_file):
        # 'Dangerous': MJ's album track + two other artists' tracks, all poisoned VA
        make_tagged_file(filename="crate/singles/Michael Jackson - Remember the Time.mp3",
                         artist="Michael Jackson", albumartist=VA, album="Dangerous",
                         title="Remember the Time", track=5)
        make_tagged_file(filename="crate/singles/TYuS - Dangerous.mp3",
                         artist="TYuS", albumartist=VA, album="Dangerous", title="Dangerous", track=1)
        make_tagged_file(filename="crate/singles/Shay Lia - Blue.mp3",
                         artist="Shay Lia/KAYTRANADA", albumartist=VA, album="Dangerous", title="Blue", track=3)
        plan = _plan(tmp_path)
        assert plan.album_moves == []
        assert plan.va_groups == []

    def test_artists_own_tracks_stay_an_album_others_become_singles(self, tmp_path, make_tagged_file):
        # '4U': Ojerime's two tracks stay an album; the rest are singles
        make_tagged_file(filename="crate/albums/Various Artists - 4 U/01 - Ojerime - 4U.mp3",
                         artist="Ojerime", albumartist=VA, album="4 U", title="4U", track=1)
        make_tagged_file(filename="crate/albums/Various Artists - 4 U/02 - Ojerime - I Know Now (2003).mp3",
                         artist="Ojerime", albumartist=VA, album="4 U", title="I Know Now (2003)", track=2)
        for a, t in [("Nali", "4 U"), ("Pi'erre Bourne", "4U"), ("printingcounterfeits", "4u")]:
            make_tagged_file(filename=f"crate/singles/{a} - {t}.mp3",
                             artist=a, albumartist=VA, album="4 U", title=t, track=1)
        plan = _plan(tmp_path)
        album_dsts = {os.path.dirname(d) for _, d, _ in plan.album_moves}
        assert album_dsts == {os.path.join(str(tmp_path / "crate"), "albums", "Ojerime - 4 U")}
        assert len(plan.album_moves) == 2
        assert {aa for *_, aa in plan.album_moves} == {"Ojerime"}   # poisoned VA healed
        assert len(plan.tag_writes) == 2
        assert plan.singleton_moves == []


class TestCompilationsAndPeeling:
    def test_real_va_compilation_stays_together(self, tmp_path, make_tagged_file):
        for i, (a, t) in enumerate([("Teebs", "Why Like This"), ("Ahwlee", "Hold"),
                                    ("Mndsgn", "Abeja"), ("WOKE", "Light")], 1):
            make_tagged_file(filename=f"crate/albums/Various Artists - Brainfeeder X/{i:02d} - {a} - {t}.mp3",
                             artist=a, albumartist=VA, album="Brainfeeder X", title=t, track=i)
        plan = _plan(tmp_path)
        assert plan.album_moves == [] and plan.singleton_moves == []
        assert plan.split_groups == []
        assert [(g[0], g[1]) for g in plan.va_groups] == [("Brainfeeder X", 4)]

    def test_va_tagged_pile_of_same_titled_singles_is_not_a_compilation(self, tmp_path, make_tagged_file):
        for a in ["A One", "B Two", "C Three", "D Four"]:
            make_tagged_file(filename=f"crate/albums/Various Artists - Hot/01 - {a} - Hot.mp3",
                             artist=a, albumartist=VA, album="Hot", title="Hot", track=1)
        plan = _plan(tmp_path)
        assert plan.album_moves == [] and len(plan.singleton_moves) == 4

    def test_foreign_track_peeled_out_of_real_album(self, tmp_path, make_tagged_file):
        for i in range(1, 5):
            make_tagged_file(filename=f"crate/albums/Ital Tek - Control/{i:02d} - Ital Tek - T{i}.mp3",
                             artist="Ital Tek", albumartist="Ital Tek", album="Control", title=f"T{i}", track=i)
        make_tagged_file(filename="crate/albums/Ital Tek - Control/09 - Janet Jackson - Funny How Time Flies.mp3",
                         artist="Janet Jackson", albumartist="Ital Tek", album="Control",
                         title="Funny How Time Flies", track=9)
        plan = _plan(tmp_path)
        assert plan.album_moves == []
        assert [os.path.basename(d) for _, d in plan.singleton_moves] == ["Janet Jackson - Funny How Time Flies.mp3"]

    def test_feature_heavy_album_stays_one_album(self, tmp_path, make_tagged_file):
        arts = ["Run The Jewels", "Run The Jewels/Danny Brown", "Run The Jewels/Killer Mike", "Run The Jewels/Joi Bay"]
        for i, a in enumerate(arts, 1):
            make_tagged_file(filename=f"crate/albums/Run The Jewels - Run The Jewels 3/{i:02d} - x - T{i}.mp3",
                             artist=a, albumartist="Run The Jewels", album="Run The Jewels 3", title=f"T{i}", track=i)
        plan = _plan(tmp_path)
        assert plan.split_groups == [] and plan.singleton_moves == []

    def test_ambiguous_untagged_group_kept_and_reported(self, tmp_path, make_tagged_file):
        for i, a in enumerate(["A", "B", "C", "D"], 1):
            make_tagged_file(filename=f"crate/albums/mix/{i:02d} - {a} - Song{i}.mp3",
                             artist=a, albumartist=a, album="Mixtape", title=f"Song{i}", track=i)
        plan = _plan(tmp_path)
        assert [(g[0], g[1]) for g in plan.ambiguous_groups] == [("Mixtape", 4)]
        assert plan.singleton_moves == []
