"""Tests for playlists.build - TEST_PLANS.md 'playlists/build.py' section.

Written against the actual current source. playlists.build imports its
heavy dependencies (lib.catalog.indexer/matcher, lib.m3u, lib.spotify_auth,
download.spotify_api/spotify_export) directly by name, and every one of
those already has (or will have) its own real coverage elsewhere - so
build_playlists()'s own orchestration tests below fake all of them at the
playlists.build module level, the same isolation boundary used for
organize.beets_import's subprocess/preimport fakes. Only build.py's own
logic (scope selection, grouping, the rescrape-patches-only-named-rows
path, unmatched aggregation, the apply/covers gating) is under test here.
"""
import os

import pytest

import playlists.build as build_module
from playlists.build import (
    _csv_escape,
    _group_tracks_by_playlist,
    _read_csv,
    _scope_rescrape,
    _select_playlists,
    _write_csv,
    _write_unmatched,
    build_playlists,
)


PLAYLISTS_HEADER = "id,name,description,owner,public,track_count,playlist_url\n"


# --- _select_playlists -------------------------------------------------

class TestSelectPlaylistsDefaultScope:
    @pytest.mark.xfail(
        reason=(
            "known bug per TEST_PLANS.md §4 / PACKAGE_OVERVIEW.md: "
            "playlists.csv's 'owner' column holds a Spotify *display name*, "
            "but _select_playlists()'s default scope compares it directly "
            "against SPOTIFY_USER_ID (a user id) via `r.get('owner') == "
            "user_id`. A playlist actually owned by the authenticated user "
            "(display name 'Jordan Smith', id '1137489201') therefore never "
            "matches its own id, and the default 'my playlists only' scope "
            "returns nothing for it. Flip to a real test once "
            "_select_playlists() resolves the authenticated user's display "
            "name (or the real user id) before comparing against 'owner', "
            "instead of comparing SPOTIFY_USER_ID to it directly."
        ),
        strict=True,
    )
    def test_default_scope_matches_by_id_not_display_name(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPOTIFY_USER_ID", "1137489201")

        playlists_csv = tmp_path / "playlists.csv"
        playlists_csv.write_text(
            PLAYLISTS_HEADER + "PID1,My Playlist,,Jordan Smith,True,3,url1\n",
            encoding="utf-8",
        )

        selected = _select_playlists(str(playlists_csv), names=[], all_playlists=False)

        assert {row["id"] for row in selected} == {"PID1"}

    def test_default_scope_without_user_id_warns_and_returns_everything(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.delenv("SPOTIFY_USER_ID", raising=False)
        playlists_csv = tmp_path / "playlists.csv"
        playlists_csv.write_text(
            PLAYLISTS_HEADER
            + "PID1,A,,me,True,1,url1\n"
            + "PID2,B,,someone_else,True,1,url2\n",
            encoding="utf-8",
        )

        selected = _select_playlists(str(playlists_csv), names=[], all_playlists=False)

        assert {row["id"] for row in selected} == {"PID1", "PID2"}
        assert "SPOTIFY_USER_ID not set" in capsys.readouterr().out


class TestSelectPlaylistsOtherScopes:
    def test_raises_when_playlists_csv_missing(self, tmp_path):
        with pytest.raises(ValueError):
            _select_playlists(str(tmp_path / "playlists.csv"), names=[], all_playlists=False)

    def test_all_playlists_flag_returns_every_row_regardless_of_owner(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("SPOTIFY_USER_ID", "me")
        playlists_csv = tmp_path / "playlists.csv"
        playlists_csv.write_text(
            PLAYLISTS_HEADER
            + "PID1,A,,me,True,1,url1\n"
            + "PID2,B,,someone_else,True,1,url2\n",
            encoding="utf-8",
        )

        selected = _select_playlists(str(playlists_csv), names=[], all_playlists=True)

        assert {row["id"] for row in selected} == {"PID1", "PID2"}

    def test_names_scope_matches_by_id_token_and_by_name_token(self, tmp_path, monkeypatch):
        # extract_playlist_id_from_url is download.spotify_export's own
        # concern (tested there); fake it here so this test only exercises
        # _select_playlists()'s own id-vs-name branching.
        monkeypatch.setattr(
            build_module, "extract_playlist_id_from_url",
            lambda token: token[3:] if token.startswith("ID:") else "",
        )

        playlists_csv = tmp_path / "playlists.csv"
        playlists_csv.write_text(
            PLAYLISTS_HEADER
            + "37i9dQZF1DXcBWIGoYBM5Mabc,By Id,,me,True,1,url1\n"
            + "PID2,By Name,,me,True,1,url2\n"
            + "PID3,Not Selected,,me,True,1,url3\n",
            encoding="utf-8",
        )

        selected = _select_playlists(
            str(playlists_csv),
            names=["ID:37i9dQZF1DXcBWIGoYBM5Mabc", "By Name"],
            all_playlists=False,
        )

        assert {row["id"] for row in selected} == {"37i9dQZF1DXcBWIGoYBM5Mabc", "PID2"}

    def test_names_scope_overrides_all_playlists_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr(build_module, "extract_playlist_id_from_url", lambda token: "")
        playlists_csv = tmp_path / "playlists.csv"
        playlists_csv.write_text(
            PLAYLISTS_HEADER
            + "PID1,Wanted,,me,True,1,url1\n"
            + "PID2,Not Wanted,,me,True,1,url2\n",
            encoding="utf-8",
        )

        selected = _select_playlists(str(playlists_csv), names=["Wanted"], all_playlists=True)

        assert {row["id"] for row in selected} == {"PID1"}


# --- _group_tracks_by_playlist ------------------------------------------

class TestGroupTracksByPlaylist:
    def test_groups_preserving_first_seen_playlist_order(self):
        rows = [
            {"playlist_id": "B", "track_id": "1"},
            {"playlist_id": "A", "track_id": "2"},
            {"playlist_id": "B", "track_id": "3"},
        ]
        groups = _group_tracks_by_playlist(rows)
        assert list(groups.keys()) == ["B", "A"]
        assert [r["track_id"] for r in groups["B"]] == ["1", "3"]

    def test_rows_without_a_playlist_id_are_skipped(self):
        rows = [{"playlist_id": "", "track_id": "1"}, {"track_id": "2"}]
        assert _group_tracks_by_playlist(rows) == {}


# --- _csv_escape ----------------------------------------------------------

class TestCsvEscape:
    def test_plain_value_is_left_unquoted(self):
        assert _csv_escape("hello") == "hello"

    def test_value_with_a_comma_is_quoted(self):
        assert _csv_escape("a,b") == '"a,b"'

    def test_embedded_quote_is_doubled(self):
        assert _csv_escape('say "hi"') == '"say ""hi"""'


# --- _read_csv / _write_csv -----------------------------------------------

class TestReadWriteCsv:
    def test_read_csv_missing_file_returns_empty_list(self, tmp_path):
        assert _read_csv(str(tmp_path / "nope.csv")) == []

    def test_write_csv_round_trips(self, tmp_path):
        path = str(tmp_path / "out.csv")
        rows = [{"id": "P1", "name": "One", "owner": "me"}]
        _write_csv(path, rows, ("id", "name", "owner"))
        assert _read_csv(path) == rows

    def test_write_csv_failure_is_non_fatal(self, tmp_path, monkeypatch, capsys):
        path = str(tmp_path / "out.csv")

        def fail_open(*a, **kw):
            raise OSError("locked")
        monkeypatch.setattr("builtins.open", fail_open)

        _write_csv(path, [{"id": "P1"}], ("id",))  # must not raise

        assert "warning" in capsys.readouterr().out
        assert not os.path.exists(path)


# --- _write_unmatched -------------------------------------------------------

class TestWriteUnmatched:
    def test_writes_csv_and_deduped_urls(self, tmp_path):
        rows = [
            {"playlist_name": "P1", "track_id": "t1", "track_name": "Song",
             "artist_names": "Artist", "album_name": "Album", "tier_tried": 3,
             "spotify_url": "https://open.spotify.com/track/1"},
            {"playlist_name": "P1", "track_id": "t2", "track_name": "Song2",
             "artist_names": "Artist", "album_name": "Album", "tier_tried": 4,
             "spotify_url": "https://open.spotify.com/track/1"},  # dup url
        ]

        n = _write_unmatched(str(tmp_path), rows)

        assert n == 2
        csv_text = (tmp_path / "unmatched.csv").read_text(encoding="utf-8-sig")
        assert csv_text.count("\n") == 3  # header + 2 rows
        urls = (tmp_path / "unmatched_urls.txt").read_text(encoding="utf-8-sig").splitlines()
        assert urls == ["https://open.spotify.com/track/1"]

    def test_no_rows_writes_empty_files_without_erroring(self, tmp_path):
        n = _write_unmatched(str(tmp_path), [])
        assert n == 0
        assert (tmp_path / "unmatched.csv").exists()
        assert (tmp_path / "unmatched_urls.txt").read_text(encoding="utf-8-sig") == ""

    def test_write_failure_is_non_fatal(self, tmp_path, monkeypatch, capsys):
        def fail_open(*a, **kw):
            raise OSError("locked")
        monkeypatch.setattr("builtins.open", fail_open)

        n = _write_unmatched(str(tmp_path), [{"spotify_url": "x"}])  # must not raise

        assert n == 1
        assert "warning" in capsys.readouterr().out


# --- _scope_rescrape ---------------------------------------------------------

class TestScopeRescrape:
    def test_patches_only_named_playlists_leaving_others_untouched(
        self, tmp_path, monkeypatch
    ):
        exports = tmp_path
        (exports / "playlists.csv").write_text(
            PLAYLISTS_HEADER + "OLD1,Old One,,me,True,2,url1\nOLD2,Old Two,,me,True,1,url2\n",
            encoding="utf-8",
        )
        (exports / "playlist_tracks.csv").write_text(
            "playlist_id,track_id\nOLD1,t1\nOLD1,t2\nOLD2,t3\n",
            encoding="utf-8",
        )

        class FakeSp:
            def playlist(self, pid):
                return {
                    "id": pid,
                    "name": "Old One Renamed",
                    "description": "",
                    "owner": {"display_name": "me"},
                    "public": True,
                    "tracks": {"total": 1},
                    "external_urls": {"spotify": "url1-new"},
                }

        monkeypatch.setattr(
            build_module, "get_playlist_tracks",
            lambda sp, pid, name: [{"playlist_id": pid, "track_id": "t99"}],
        )

        _scope_rescrape(FakeSp(), ["Old One"], str(exports))

        metas = {m["id"]: m for m in _read_csv(str(exports / "playlists.csv"))}
        assert metas["OLD1"]["name"] == "Old One Renamed"
        assert metas["OLD2"]["name"] == "Old Two"  # untouched

        tracks_by_playlist = {}
        for t in _read_csv(str(exports / "playlist_tracks.csv")):
            tracks_by_playlist.setdefault(t["playlist_id"], []).append(t["track_id"])
        assert tracks_by_playlist["OLD1"] == ["t99"]  # replaced
        assert tracks_by_playlist["OLD2"] == ["t3"]   # untouched

    def test_unresolvable_name_token_warns_and_writes_nothing(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(build_module, "extract_playlist_id_from_url", lambda token: "")
        exports = tmp_path
        (exports / "playlists.csv").write_text(PLAYLISTS_HEADER, encoding="utf-8")

        write_calls = []
        monkeypatch.setattr(build_module, "_write_csv", lambda *a, **kw: write_calls.append(a))

        _scope_rescrape(object(), ["Nonexistent"], str(exports))

        assert write_calls == []
        out = capsys.readouterr().out
        assert "can't rescrape by name" in out
        assert "Nonexistent" in out


# --- build_playlists() orchestration ----------------------------------------

class TestBuildPlaylistsOrchestration:
    def _fixture_dirs(self, tmp_path):
        exports = tmp_path / "exports"
        exports.mkdir()
        playlists_path = tmp_path / "playlists"
        crate = tmp_path / "crate"
        crate.mkdir()
        (exports / "playlists.csv").write_text(
            PLAYLISTS_HEADER
            + "P1,Playlist One,,me,True,2,url1\n"
            + "P2,Playlist Two,,me,True,1,url2\n",
            encoding="utf-8",
        )
        (exports / "playlist_tracks.csv").write_text(
            "playlist_id,track_id,track_name,artist_names,album_name,spotify_url\n"
            "P1,t1,Song A,Artist A,Album A,u1\n"
            "P1,t2,Song B,Artist B,Album B,u2\n"
            "P2,t3,Song C,Artist C,Album C,u3\n",
            encoding="utf-8",
        )
        return exports, playlists_path, crate

    def _wire_common_fakes(self, monkeypatch, match_map, m3u8_calls):
        # get_index/MatchIndex come from lib.catalog.indexer/matcher, which
        # get their own real coverage - here they're just pass-throughs so
        # match_rows() below is the only thing build_playlists() sees.
        monkeypatch.setattr(build_module, "get_index", lambda *a, **kw: "INDEX")
        monkeypatch.setattr(build_module, "MatchIndex", lambda index: index)
        monkeypatch.setattr(build_module, "safe_name", lambda name: name)

        def fake_match_rows(rows, index=None, verbose=False):
            return [match_map[r["track_id"]](r) for r in rows]
        monkeypatch.setattr(build_module, "match_rows", fake_match_rows)

        def fake_write_m3u8(path, entries):
            m3u8_calls.append((path, entries))
            with open(path, "w", encoding="utf-8") as f:
                f.write("stub")
        monkeypatch.setattr(build_module, "write_m3u8", fake_write_m3u8)

    @staticmethod
    def _matched(row):
        return {"row": row, "path": f"/crate/{row['track_id']}.mp3", "length": 200, "tier": 1}

    @staticmethod
    def _unmatched(row):
        return {"row": row, "path": None, "length": 0, "tier": 6}

    def test_apply_writes_m3u8_only_for_playlists_with_matches(self, tmp_path, monkeypatch):
        exports, playlists_path, crate = self._fixture_dirs(tmp_path)
        m3u8_calls = []
        match_map = {"t1": self._matched, "t2": self._unmatched, "t3": self._unmatched}
        self._wire_common_fakes(monkeypatch, match_map, m3u8_calls)

        build_playlists(apply=True, playlists_path=str(playlists_path),
                         archive_path=str(crate), exports_dir=str(exports))

        assert len(m3u8_calls) == 1  # only P1 had a match; P2 had none
        path, entries = m3u8_calls[0]
        assert path == os.path.join(str(playlists_path), "Playlist One.m3u8")
        assert [e["track_id"] for e in entries] == ["t1"]
        assert os.path.exists(path)

        unmatched_rows = _read_csv(str(exports / "unmatched.csv"))
        assert {r["track_id"] for r in unmatched_rows} == {"t2", "t3"}

    def test_preview_mode_writes_no_m3u8_files(self, tmp_path, monkeypatch):
        exports, playlists_path, crate = self._fixture_dirs(tmp_path)
        m3u8_calls = []
        match_map = {"t1": self._matched, "t2": self._matched, "t3": self._matched}
        self._wire_common_fakes(monkeypatch, match_map, m3u8_calls)

        build_playlists(apply=False, playlists_path=str(playlists_path),
                         archive_path=str(crate), exports_dir=str(exports))

        assert m3u8_calls == []
        assert playlists_path.exists()          # the dir itself is still created...
        assert list(playlists_path.iterdir()) == []  # ...but nothing is written into it

    def test_covers_flag_downloads_cover_only_for_written_playlists(self, tmp_path, monkeypatch):
        exports, playlists_path, crate = self._fixture_dirs(tmp_path)
        m3u8_calls = []
        cover_calls = []
        match_map = {"t1": self._matched, "t2": self._unmatched, "t3": self._unmatched}
        self._wire_common_fakes(monkeypatch, match_map, m3u8_calls)
        monkeypatch.setattr(build_module, "authenticate_user", lambda: "FAKE_SP")
        monkeypatch.setattr(
            build_module, "_download_cover",
            lambda sp, pid, dest: cover_calls.append((sp, pid, dest)) or True,
        )

        build_playlists(apply=True, covers=True, playlists_path=str(playlists_path),
                         archive_path=str(crate), exports_dir=str(exports))

        # P2 never got a .m3u8 (no matches), so it should never get a cover either
        assert cover_calls == [("FAKE_SP", "P1", os.path.join(str(playlists_path), "Playlist One.jpg"))]

    def test_raises_when_archive_path_does_not_exist(self, tmp_path, monkeypatch):
        exports, playlists_path, _crate = self._fixture_dirs(tmp_path)
        m3u8_calls = []
        self._wire_common_fakes(monkeypatch, {}, m3u8_calls)

        with pytest.raises(ValueError):
            build_playlists(apply=False, playlists_path=str(playlists_path),
                             archive_path=str(tmp_path / "does_not_exist"),
                             exports_dir=str(exports))
