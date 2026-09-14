"""Tests for download.spotify_api - no TEST_PLANS.md section of its own
(not in the original inventory), added proactively: get_user_playlists()'s
owner_id fix (see playlists/build.py's _select_playlists()) had no
coverage anywhere, and the rest of this module - track extraction,
pagination, the two-pass dedup, csv export - didn't either.

FakeSp below is a minimal spotipy-shaped fake: given a list of pre-built
pages up front, .next() just advances a cursor through them, ignoring
whatever 'results' object it's handed back (a real spotipy client uses
that to know which url to fetch next; nothing here needs that, since the
pages are already known).

normalize_title/primary_artist (from lib.text) are mocked for the dedup
tests below rather than relied on for real - they already have their own
real coverage in tests/lib/test_text.py, and mocking them here means the
dedup tests only exercise merge_and_deduplicate()'s own merge/sort/keep
logic, not lib.text's normalization rules.
"""
import pytest

import download.spotify_api as spotify_api_module
from download.spotify_api import (
    _extract_track,
    _fuzzy_key,
    export_manifest_as_txt,
    export_to_csv,
    get_export_dir,
    get_liked_songs,
    get_playlist_tracks,
    get_user_playlists,
    merge_and_deduplicate,
)


class FakeSp:
    def __init__(self, pages, current_user=None):
        self._pages = list(pages)
        self._idx = 0
        self._current_user = current_user if current_user is not None else {}

    def _first_page(self):
        self._idx = 0
        return self._pages[0]

    def current_user(self):
        return self._current_user

    def current_user_playlists(self, limit=50):
        return self._first_page()

    def playlist_tracks(self, playlist_id, limit=100):
        return self._first_page()

    def current_user_saved_tracks(self, limit=50):
        return self._first_page()

    def next(self, results):
        self._idx += 1
        return self._pages[self._idx]


# --- get_user_playlists ------------------------------------------------

class TestGetUserPlaylists:
    @staticmethod
    def _playlist(pid, owner_display, owner_id, name=None, url=None):
        return {
            "id": pid,
            "name": name or f"Playlist {pid}",
            "description": "",
            "public": True,
            "owner": {"display_name": owner_display, "id": owner_id},
            "tracks": {"total": 3},
            "external_urls": {
                "spotify": url if url is not None else f"https://open.spotify.com/playlist/{pid}"
            },
        }

    def test_maps_playlist_fields_including_owner_id(self):
        """owner_id must land in the returned row, not just be used
        internally for the my_playlists_only pre-filter - this is the
        column playlists.build._select_playlists()'s default scope now
        filters on."""
        sp = FakeSp(pages=[{
            "items": [self._playlist("P1", "Jordan Smith", "1137489201")],
            "next": None,
        }])
        result = get_user_playlists(sp)
        assert result == [{
            "id": "P1", "name": "Playlist P1", "description": "", "owner": "Jordan Smith",
            "owner_id": "1137489201", "public": True, "track_count": 3,
            "playlist_url": "https://open.spotify.com/playlist/P1",
        }]

    def test_pagination_follows_next(self):
        sp = FakeSp(pages=[
            {"items": [self._playlist("P1", "Me", "U1")], "next": True},
            {"items": [self._playlist("P2", "Me", "U1")], "next": None},
        ])
        result = get_user_playlists(sp)
        assert [p["id"] for p in result] == ["P1", "P2"]

    def test_my_playlists_only_filters_by_owner_id_not_display_name(self):
        sp = FakeSp(
            pages=[{
                "items": [
                    self._playlist("MINE", "Jordan Smith", "1137489201"),
                    # same display name, different id - must not match on name
                    self._playlist("NOT_MINE", "Jordan Smith", "999999999"),
                ],
                "next": None,
            }],
            current_user={"id": "1137489201"},
        )
        result = get_user_playlists(sp, my_playlists_only=True)
        assert [p["id"] for p in result] == ["MINE"]

    def test_current_user_lookup_failure_warns_and_returns_everything_unfiltered(self, capsys):
        """Documented fail-open behavior, not a crash: if resolving the
        authenticated user's own id fails, my_playlists_only silently has
        no effect rather than raising or returning nothing. Worth pinning
        explicitly since it's a surprising default."""
        class BrokenCurrentUserSp(FakeSp):
            def current_user(self):
                raise RuntimeError("expired token")

        sp = BrokenCurrentUserSp(pages=[{
            "items": [
                self._playlist("P1", "Someone", "111"),
                self._playlist("P2", "Someone Else", "222"),
            ],
            "next": None,
        }])
        result = get_user_playlists(sp, my_playlists_only=True)
        assert [p["id"] for p in result] == ["P1", "P2"]
        assert "could not get current user id for filtering" in capsys.readouterr().out

    def test_missing_external_urls_defaults_to_empty_playlist_url(self):
        playlist = self._playlist("P1", "Me", "U1")
        del playlist["external_urls"]
        sp = FakeSp(pages=[{"items": [playlist], "next": None}])
        result = get_user_playlists(sp)
        assert result[0]["playlist_url"] == ""


# --- _extract_track ----------------------------------------------------

class TestExtractTrack:
    def test_extracts_expected_fields(self):
        item = {
            "added_at": "2024-01-01T00:00:00Z",
            "added_by": {"id": "user123"},
            "track": {
                "id": "T1", "name": "Song", "duration_ms": 12345, "explicit": True,
                "popularity": 77, "track_number": 3, "disc_number": 1, "is_local": False,
                "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
                "album": {"name": "Album X"},
                "external_urls": {"spotify": "https://open.spotify.com/track/T1"},
            },
        }
        entry = _extract_track(item, "PID1", "My Playlist")
        assert entry == {
            "playlist_id": "PID1", "playlist_name": "My Playlist", "track_id": "T1",
            "track_name": "Song", "artist_names": "Artist A, Artist B", "album_name": "Album X",
            "duration_ms": 12345, "explicit": True, "popularity": 77,
            "added_at": "2024-01-01T00:00:00Z", "added_by": "user123",
            "spotify_url": "https://open.spotify.com/track/T1",
            "track_number": 3, "disc_number": 1, "is_local": False,
        }

    def test_returns_none_when_track_is_missing(self):
        # Spotify represents a removed/local-only track as track: null -
        # must not raise, just drop it.
        assert _extract_track({"track": None}, "PID1", "My Playlist") is None
        assert _extract_track({}, "PID1", "My Playlist") is None

    def test_missing_added_by_defaults_to_none(self):
        item = {"track": {"id": "T1", "name": "Song", "artists": []}}
        entry = _extract_track(item, "PID1", "My Playlist")
        assert entry["added_by"] is None

    def test_missing_spotify_url_defaults_to_empty(self):
        item = {"track": {"id": "T1", "name": "Song", "artists": []}}
        entry = _extract_track(item, "PID1", "My Playlist")
        assert entry["spotify_url"] == ""

    def test_no_artists_gives_empty_artist_names(self):
        item = {"track": {"id": "T1", "name": "Song", "artists": []}}
        entry = _extract_track(item, "PID1", "My Playlist")
        assert entry["artist_names"] == ""


# --- get_playlist_tracks / get_liked_songs -------------------------------

class TestGetPlaylistTracks:
    def test_pagination_and_track_extraction(self):
        item1 = {"track": {"id": "T1", "name": "Song 1", "artists": []}}
        item2 = {"track": {"id": "T2", "name": "Song 2", "artists": []}}
        sp = FakeSp(pages=[
            {"items": [item1], "next": True},
            {"items": [item2], "next": None},
        ])
        result = get_playlist_tracks(sp, "PID1", "My Playlist")
        assert [t["track_id"] for t in result] == ["T1", "T2"]
        assert all(t["playlist_id"] == "PID1" and t["playlist_name"] == "My Playlist" for t in result)

    def test_skips_items_with_no_track(self):
        items = [{"track": None}, {"track": {"id": "T1", "name": "Song", "artists": []}}]
        sp = FakeSp(pages=[{"items": items, "next": None}])
        result = get_playlist_tracks(sp, "PID1", "My Playlist")
        assert [t["track_id"] for t in result] == ["T1"]


class TestGetLikedSongs:
    def test_uses_liked_songs_playlist_id_and_name(self):
        item = {"track": {"id": "T1", "name": "Song", "artists": []}}
        sp = FakeSp(pages=[{"items": [item], "next": None}])
        result = get_liked_songs(sp)
        assert result[0]["playlist_id"] == "liked_songs"
        assert result[0]["playlist_name"] == "Liked Songs"

    def test_pagination_follows_next(self):
        item1 = {"track": {"id": "T1", "name": "Song 1", "artists": []}}
        item2 = {"track": {"id": "T2", "name": "Song 2", "artists": []}}
        sp = FakeSp(pages=[
            {"items": [item1], "next": True},
            {"items": [item2], "next": None},
        ])
        result = get_liked_songs(sp)
        assert [t["track_id"] for t in result] == ["T1", "T2"]


# --- _fuzzy_key / merge_and_deduplicate ----------------------------------

@pytest.fixture
def deterministic_normalization(monkeypatch):
    """lib.text's real normalize_title/primary_artist already have their
    own tests - swap in trivial, deterministic stand-ins so the dedup
    tests below only depend on merge_and_deduplicate()'s own logic."""
    monkeypatch.setattr(spotify_api_module, "normalize_title", str.lower)
    monkeypatch.setattr(spotify_api_module, "primary_artist", lambda s: s.split(",")[0].strip())


class TestFuzzyKey:
    def test_key_combines_normalized_primary_artist_and_title(self, deterministic_normalization):
        track = {"artist_names": "Artist A, Artist B", "track_name": "Song Title"}
        assert _fuzzy_key(track) == "artist a|||song title"


class TestMergeAndDeduplicate:
    def test_id_dedup_merges_playlist_membership(self, deterministic_normalization):
        tracks = [
            {"track_id": "t1", "track_name": "Song", "artist_names": "A",
             "playlist_name": "P1", "playlist_id": "PID1", "popularity": 50, "spotify_url": "u1"},
            {"track_id": "t1", "track_name": "Song", "artist_names": "A",
             "playlist_name": "P2", "playlist_id": "PID2", "popularity": 50, "spotify_url": "u1"},
        ]
        result = merge_and_deduplicate(tracks, [])
        assert len(result) == 1
        assert result[0]["playlist_names"] == "P1; P2"
        assert result[0]["playlist_ids"] == "PID1; PID2"
        assert result[0]["playlist_count"] == 2

    def test_tracks_without_track_id_are_dropped(self, deterministic_normalization):
        tracks = [{"track_id": "", "track_name": "X", "artist_names": "A", "spotify_url": ""}]
        assert merge_and_deduplicate(tracks, []) == []

    def test_playlists_and_liked_songs_are_combined(self, deterministic_normalization):
        playlists_data = [{"track_id": "t1", "track_name": "A", "artist_names": "X",
                            "playlist_name": "P1", "playlist_id": "PID1",
                            "popularity": 10, "spotify_url": "u1"}]
        liked_data = [{"track_id": "t2", "track_name": "B", "artist_names": "Y",
                        "playlist_name": "Liked Songs", "playlist_id": "liked_songs",
                        "popularity": 10, "spotify_url": "u2"}]
        result = merge_and_deduplicate(playlists_data, liked_data)
        assert {t["track_id"] for t in result} == {"t1", "t2"}

    def test_fuzzy_dedup_keeps_more_popular_track_and_merges_playlists(self, deterministic_normalization):
        # different track_id (survives id-dedup) but same normalized
        # primary artist + title (a remaster/regional-version collision)
        tracks = [
            {"track_id": "t1", "track_name": "Song", "artist_names": "Artist A",
             "playlist_name": "P1", "playlist_id": "PID1", "popularity": 40, "spotify_url": "u1"},
            {"track_id": "t2", "track_name": "song", "artist_names": "artist a",
             "playlist_name": "P2", "playlist_id": "PID2", "popularity": 90, "spotify_url": "u2"},
        ]
        result = merge_and_deduplicate(tracks, [])
        assert len(result) == 1
        kept = result[0]
        assert kept["track_id"] == "t2"          # the more popular of the two
        assert kept["playlist_names"] == "P1; P2"  # membership merged from both
        assert kept["playlist_count"] == 2

    def test_fuzzy_dedup_merges_playlists_into_existing_when_it_stays_canonical(
        self, deterministic_normalization
    ):
        # same collision, but the *first*-seen (already more popular)
        # track should stay canonical and still pick up the loser's
        # playlist membership.
        tracks = [
            {"track_id": "t1", "track_name": "Song", "artist_names": "Artist A",
             "playlist_name": "P1", "playlist_id": "PID1", "popularity": 90, "spotify_url": "u1"},
            {"track_id": "t2", "track_name": "song", "artist_names": "artist a",
             "playlist_name": "P2", "playlist_id": "PID2", "popularity": 40, "spotify_url": "u2"},
        ]
        result = merge_and_deduplicate(tracks, [])
        assert len(result) == 1
        kept = result[0]
        assert kept["track_id"] == "t1"
        assert kept["playlist_names"] == "P1; P2"
        assert kept["playlist_count"] == 2

    def test_sorted_by_track_name_case_insensitive(self, deterministic_normalization):
        tracks = [
            {"track_id": "t1", "track_name": "Zebra", "artist_names": "A",
             "playlist_name": "P1", "playlist_id": "PID1", "popularity": 10, "spotify_url": "u1"},
            {"track_id": "t2", "track_name": "apple", "artist_names": "B",
             "playlist_name": "P1", "playlist_id": "PID1", "popularity": 10, "spotify_url": "u2"},
        ]
        result = merge_and_deduplicate(tracks, [])
        assert [t["track_name"] for t in result] == ["apple", "Zebra"]


# --- export_to_csv -------------------------------------------------------

class TestExportToCsv:
    def test_writes_header_and_rows_from_dict_keys(self, tmp_path):
        data = [
            {"id": "P1", "name": "One", "owner_id": "123"},
            {"id": "P2", "name": "Two", "owner_id": "456"},
        ]
        export_to_csv(data, "out.csv", str(tmp_path))
        lines = (tmp_path / "out.csv").read_text(encoding="utf-8-sig").splitlines()
        assert lines[0] == "id,name,owner_id"
        assert lines[1] == "P1,One,123"
        assert lines[2] == "P2,Two,456"

    def test_empty_data_writes_empty_file_without_erroring(self, tmp_path, capsys):
        export_to_csv([], "empty.csv", str(tmp_path))
        assert (tmp_path / "empty.csv").exists()
        assert "no data to export" in capsys.readouterr().out


# --- export_manifest_as_txt -----------------------------------------------

class TestExportManifestAsTxt:
    def test_writes_only_nonempty_spotify_urls(self, tmp_path):
        tracks = [
            {"spotify_url": "https://open.spotify.com/track/AAA"},
            {"spotify_url": ""},
            {"spotify_url": "https://open.spotify.com/track/BBB"},
        ]
        export_manifest_as_txt(tracks, str(tmp_path))
        lines = (tmp_path / "spotify_manifest_urls.txt").read_text(encoding="utf-8").splitlines()
        assert lines == [
            "https://open.spotify.com/track/AAA",
            "https://open.spotify.com/track/BBB",
        ]

    def test_custom_filename_used(self, tmp_path):
        """The scoped multi-playlist export path (spotify_export.py's
        export_playlists()) relies on this so it doesn't clobber the
        full-library spotify_manifest_urls.txt in the same export dir."""
        tracks = [{"spotify_url": "u1"}]
        export_manifest_as_txt(tracks, str(tmp_path), filename="playlists_manifest_urls.txt")
        assert (tmp_path / "playlists_manifest_urls.txt").exists()
        assert not (tmp_path / "spotify_manifest_urls.txt").exists()


# --- get_export_dir --------------------------------------------------------

class TestGetExportDir:
    def test_delegates_to_lib_paths_exports_dir(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            spotify_api_module, "exports_dir",
            lambda cli=None: calls.append(cli) or "/resolved",
        )
        result = get_export_dir("/base")
        assert result == "/resolved"
        assert calls == ["/base"]
