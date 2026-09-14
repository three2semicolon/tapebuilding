"""Tests for download.spotify_export / download.spotify_api -
TEST_PLANS.md 'download/spotify_export.py + download/spotify_api.py'
section.

Written against the actual current source. No real spotipy client is used
anywhere here - FakeSpotify below is a minimal stand-in supporting only the
handful of methods these two modules actually call (current_user,
current_user_playlists, playlist_tracks, current_user_saved_tracks,
playlist, next).

Pagination (sp.next()) is deliberately NOT exercised here: every fixture
page below has no 'next' key, so the `while results: ... if
results.get('next'): results = sp.next(...) else break` loop in
get_user_playlists/get_playlist_tracks/get_liked_songs always takes the
break branch on the first page. That loop isn't called out in
TEST_PLANS.md for this module, and FakeSpotify.next() raises if it's ever
actually reached - so a regression that broke the loop's termination
condition would fail loudly here even without a dedicated pagination test.
"""
import csv

import pytest

from download.spotify_export import (
    extract_playlist_id_from_url,
    export_specific_playlist,
    export_playlists,
    export_all_data,
)
from download.spotify_api import (
    merge_and_deduplicate,
    get_export_dir,
)


def _track_item(track_id, name='Song', artists=('Artist',), album='Album',
                 duration_ms=200000, popularity=50, spotify_url=None, is_local=False):
    if spotify_url is None:
        spotify_url = f'https://open.spotify.com/track/{track_id}'
    return {
        'track': {
            'id': track_id,
            'name': name,
            'artists': [{'name': a} for a in artists],
            'album': {'name': album},
            'duration_ms': duration_ms,
            'explicit': False,
            'popularity': popularity,
            'track_number': 1,
            'disc_number': 1,
            'is_local': is_local,
            'external_urls': {'spotify': spotify_url},
        },
        'added_at': '2024-01-01T00:00:00Z',
        'added_by': {'id': 'someone'},
    }


def _playlist_row(pid, name, owner_id='me', owner_display='Me'):
    return {
        'id': pid,
        'name': name,
        'description': '',
        'owner': {'id': owner_id, 'display_name': owner_display},
        'public': True,
        'tracks': {'total': 0},
        'external_urls': {'spotify': f'https://open.spotify.com/playlist/{pid}'},
    }


class FakeSpotify:
    """Single-page-only fake covering every spotipy method
    spotify_export.py / spotify_api.py call. See module docstring for why
    pagination isn't modeled - next() raises if it's ever hit."""

    def __init__(self, playlists=None, tracks_by_playlist=None, saved_tracks=None,
                 playlist_lookup=None, user=None):
        self._playlists = playlists if playlists is not None else []
        self._tracks_by_playlist = tracks_by_playlist or {}
        self._saved_tracks = saved_tracks if saved_tracks is not None else []
        self._playlist_lookup = playlist_lookup or {}
        self._user = user or {'id': 'me', 'display_name': 'Test User'}
        self.playlist_calls = []

    def current_user(self):
        return self._user

    def current_user_playlists(self, limit=50):
        return {'items': self._playlists}

    def playlist_tracks(self, playlist_id, limit=100):
        return {'items': self._tracks_by_playlist.get(playlist_id, [])}

    def current_user_saved_tracks(self, limit=50):
        return {'items': self._saved_tracks}

    def playlist(self, playlist_id):
        self.playlist_calls.append(playlist_id)
        return self._playlist_lookup[playlist_id]

    def next(self, results):
        raise AssertionError(
            "next() should never be called - no fixture page in this file "
            "sets a 'next' key, so the pagination loop should always break "
            "on the first page."
        )


class TestExtractPlaylistIdFromUrl:
    def test_strips_domain_from_plain_playlist_url(self):
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        assert extract_playlist_id_from_url(url) == "37i9dQZF1DXcBWIGoYBM5M"

    def test_strips_query_params(self):
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc123"
        assert extract_playlist_id_from_url(url) == "37i9dQZF1DXcBWIGoYBM5M"

    def test_handles_spotify_uri_form(self):
        assert extract_playlist_id_from_url("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M") == "37i9dQZF1DXcBWIGoYBM5M"

    def test_bare_id_passes_through_unchanged(self):
        assert extract_playlist_id_from_url("37i9dQZF1DXcBWIGoYBM5M") == "37i9dQZF1DXcBWIGoYBM5M"

    def test_track_url_is_not_specially_handled(self):
        """Neither branch's substring/prefix check matches a track URL, so
        it falls through to the bare-passthrough else and comes back
        unchanged - extract_playlist_id_from_url() doesn't validate that
        what it's given is actually a playlist. Documents current
        behavior, not a claim that it's ideal."""
        track_url = "https://open.spotify.com/track/AAA"
        assert extract_playlist_id_from_url(track_url) == track_url


class TestMergeAndDeduplicate:
    def test_exact_dedup_merges_playlist_membership_by_track_id(self):
        t1 = {'track_id': 'id1', 'track_name': 'Song', 'artist_names': 'Artist',
              'album_name': 'Album', 'popularity': 50, 'spotify_url': 'https://x',
              'playlist_name': 'Playlist A', 'playlist_id': 'pA'}
        t2 = {**t1, 'playlist_name': 'Playlist B', 'playlist_id': 'pB'}

        result = merge_and_deduplicate([t1, t2], [])

        assert len(result) == 1
        assert result[0]['playlist_count'] == 2
        assert set(result[0]['playlist_names'].split('; ')) == {'Playlist A', 'Playlist B'}

    def test_tracks_without_a_track_id_are_dropped_entirely(self):
        no_id = {'track_id': '', 'track_name': 'No ID Song', 'artist_names': 'Artist'}
        assert merge_and_deduplicate([no_id], []) == []

    def test_fuzzy_dedup_keeps_the_more_popular_of_two_remaster_versions(self):
        original = {'track_id': 'orig', 'track_name': 'Anthem', 'artist_names': 'Nova',
                    'popularity': 40, 'spotify_url': 'https://orig',
                    'playlist_name': 'Old Favorites', 'playlist_id': 'p1'}
        remaster = {'track_id': 'remaster', 'track_name': 'Anthem', 'artist_names': 'Nova',
                    'popularity': 90, 'spotify_url': 'https://remaster',
                    'playlist_name': 'New Favorites', 'playlist_id': 'p2'}

        result = merge_and_deduplicate([original, remaster], [])

        assert len(result) == 1
        assert result[0]['track_id'] == 'remaster'

    def test_fuzzy_dedup_merges_playlist_membership_from_the_dropped_duplicate(self):
        original = {'track_id': 'orig', 'track_name': 'Anthem', 'artist_names': 'Nova',
                    'popularity': 40, 'spotify_url': 'https://orig',
                    'playlist_name': 'Old Favorites', 'playlist_id': 'p1'}
        remaster = {'track_id': 'remaster', 'track_name': 'Anthem', 'artist_names': 'Nova',
                    'popularity': 90, 'spotify_url': 'https://remaster',
                    'playlist_name': 'New Favorites', 'playlist_id': 'p2'}

        result = merge_and_deduplicate([original, remaster], [])

        assert set(result[0]['playlist_names'].split('; ')) == {'Old Favorites', 'New Favorites'}

    def test_equal_popularity_tie_keeps_the_first_seen_track(self):
        first = {'track_id': 'first', 'track_name': 'Tie', 'artist_names': 'A',
                 'popularity': 50, 'spotify_url': 'https://first',
                 'playlist_name': 'P1', 'playlist_id': 'p1'}
        second = {'track_id': 'second', 'track_name': 'Tie', 'artist_names': 'A',
                  'popularity': 50, 'spotify_url': 'https://second',
                  'playlist_name': 'P2', 'playlist_id': 'p2'}

        result = merge_and_deduplicate([first, second], [])

        assert result[0]['track_id'] == 'first'

    def test_liked_songs_are_merged_in_alongside_playlist_tracks(self):
        playlist_track = {'track_id': 'p1', 'track_name': 'A Song', 'artist_names': 'Artist',
                          'popularity': 10, 'spotify_url': 'https://p1',
                          'playlist_name': 'My Playlist', 'playlist_id': 'pl1'}
        liked_track = {'track_id': 'l1', 'track_name': 'B Song', 'artist_names': 'Artist',
                       'popularity': 10, 'spotify_url': 'https://l1',
                       'playlist_name': 'Liked Songs', 'playlist_id': 'liked_songs'}

        result = merge_and_deduplicate([playlist_track], [liked_track])

        assert {t['track_id'] for t in result} == {'p1', 'l1'}

    def test_result_is_sorted_by_track_name_case_insensitively(self):
        tracks = [
            {'track_id': 'a', 'track_name': 'zebra', 'artist_names': 'X', 'popularity': 1,
             'spotify_url': 'https://a', 'playlist_name': 'P', 'playlist_id': 'p'},
            {'track_id': 'b', 'track_name': 'Apple', 'artist_names': 'X', 'popularity': 1,
             'spotify_url': 'https://b', 'playlist_name': 'P', 'playlist_id': 'p'},
        ]

        result = merge_and_deduplicate(tracks, [])

        assert [t['track_name'] for t in result] == ['Apple', 'zebra']


class TestGetExportDir:
    def test_delegates_to_lib_paths_exports_dir_with_cli_kwarg(self, monkeypatch):
        called_with = {}

        def fake_exports_dir(cli=None):
            called_with['cli'] = cli
            return '/resolved/exports'

        monkeypatch.setattr('download.spotify_api.exports_dir', fake_exports_dir)
        result = get_export_dir(base_dir='/explicit/base')

        assert result == '/resolved/exports'
        assert called_with['cli'] == '/explicit/base'

    def test_default_base_dir_is_none(self, monkeypatch):
        called_with = {}
        monkeypatch.setattr(
            'download.spotify_api.exports_dir',
            lambda cli=None: called_with.setdefault('cli', cli),
        )
        get_export_dir()
        assert called_with['cli'] is None


class TestExportSpecificPlaylist:
    def test_writes_per_playlist_csv_and_txt(self, tmp_path):
        sp = FakeSpotify(
            tracks_by_playlist={'pid1': [_track_item('t1', name='Song One')]},
            playlist_lookup={'pid1': {'name': 'My Cool Mix'}},
        )
        tracks = export_specific_playlist(sp, 'pid1', str(tmp_path))

        assert len(tracks) == 1
        assert (tmp_path / 'playlist_My_Cool_Mix.csv').exists()
        assert (tmp_path / 'playlist_My_Cool_Mix_urls.txt').exists()

    def test_sanitizes_playlist_name_for_filename(self, tmp_path):
        sp = FakeSpotify(
            tracks_by_playlist={'pid1': []},
            playlist_lookup={'pid1': {'name': 'Chill: Vibes 2024!'}},
        )
        export_specific_playlist(sp, 'pid1', str(tmp_path))
        # ':' and '!' are stripped (not alnum/space/-/_), spaces -> underscores
        assert (tmp_path / 'playlist_Chill_Vibes_2024.csv').exists()

    def test_per_playlist_txt_includes_a_blank_line_for_tracks_without_a_url(self, tmp_path):
        """Unlike export_manifest_as_txt() (which filters out blank
        spotify_urls before writing), export_specific_playlist()'s own txt
        writer does not - a local/no-url track produces a blank line here.
        Documents current behavior rather than assuming it's a bug; see
        TODO.md for whether this is worth reconciling with
        export_manifest_as_txt()'s filtering."""
        sp = FakeSpotify(
            tracks_by_playlist={'pid1': [_track_item('t1', spotify_url='')]},
            playlist_lookup={'pid1': {'name': 'Local Mix'}},
        )
        export_specific_playlist(sp, 'pid1', str(tmp_path))

        lines = (tmp_path / 'playlist_Local_Mix_urls.txt').read_text(encoding='utf-8').splitlines(keepends=True)
        assert lines == ['\n']

    def test_returns_empty_list_and_does_not_raise_on_api_error(self, tmp_path):
        class BoomingSpotify(FakeSpotify):
            def playlist(self, playlist_id):
                raise RuntimeError("api exploded")

        result = export_specific_playlist(BoomingSpotify(), 'pid1', str(tmp_path))
        assert result == []


class TestExportPlaylists:
    def test_writes_scoped_manifest_filenames_not_full_library_ones(self, tmp_path):
        sp = FakeSpotify(
            tracks_by_playlist={
                'pid1': [_track_item('t1', name='Song One')],
                'pid2': [_track_item('t2', name='Song Two')],
            },
            playlist_lookup={
                'pid1': {'name': 'Mix One'},
                'pid2': {'name': 'Mix Two'},
            },
        )
        export_playlists(sp, ['pid1', 'pid2'], str(tmp_path))

        assert (tmp_path / 'playlists_manifest.csv').exists()
        assert (tmp_path / 'playlists_manifest_urls.txt').exists()
        assert not (tmp_path / 'spotify_manifest.csv').exists()
        assert not (tmp_path / 'spotify_manifest_urls.txt').exists()

    def test_does_not_clobber_a_pre_existing_full_library_export(self, tmp_path):
        (tmp_path / 'spotify_manifest.csv').write_text('untouched\n', encoding='utf-8')
        (tmp_path / 'spotify_manifest_urls.txt').write_text('untouched\n', encoding='utf-8')

        sp = FakeSpotify(
            tracks_by_playlist={'pid1': [_track_item('t1')]},
            playlist_lookup={'pid1': {'name': 'Mix'}},
        )
        export_playlists(sp, ['pid1'], str(tmp_path))

        assert (tmp_path / 'spotify_manifest.csv').read_text(encoding='utf-8') == 'untouched\n'
        assert (tmp_path / 'spotify_manifest_urls.txt').read_text(encoding='utf-8') == 'untouched\n'

    def test_duplicate_identifiers_are_fetched_only_once(self, tmp_path):
        sp = FakeSpotify(
            tracks_by_playlist={'pid1': [_track_item('t1')]},
            playlist_lookup={'pid1': {'name': 'Mix'}},
        )
        export_playlists(sp, ['pid1', 'pid1'], str(tmp_path))
        assert sp.playlist_calls == ['pid1']

    def test_manifest_merges_a_track_shared_across_playlists_into_one_row(self, tmp_path):
        sp = FakeSpotify(
            tracks_by_playlist={
                'pid1': [_track_item('shared', name='Shared Song')],
                'pid2': [_track_item('shared', name='Shared Song')],
            },
            playlist_lookup={
                'pid1': {'name': 'Mix One'},
                'pid2': {'name': 'Mix Two'},
            },
        )
        export_playlists(sp, ['pid1', 'pid2'], str(tmp_path))

        with open(tmp_path / 'playlists_manifest.csv', newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1


class TestExportAllData:
    def test_writes_full_library_filenames_not_scoped_ones(self, tmp_path):
        sp = FakeSpotify(
            playlists=[_playlist_row('pid1', 'Mix')],
            tracks_by_playlist={'pid1': [_track_item('t1')]},
            saved_tracks=[_track_item('t2', name='Liked One')],
        )
        export_all_data(sp, str(tmp_path))

        for name in ('playlists.csv', 'playlist_tracks.csv', 'liked_songs.csv',
                     'spotify_manifest.csv', 'spotify_manifest_urls.txt'):
            assert (tmp_path / name).exists(), name
        assert not (tmp_path / 'playlists_manifest.csv').exists()

    def test_my_playlists_only_filters_by_current_user_id(self, tmp_path):
        sp = FakeSpotify(
            playlists=[
                _playlist_row('mine', 'Mine', owner_id='me', owner_display='Me'),
                _playlist_row('theirs', 'Theirs', owner_id='someone_else', owner_display='Someone'),
            ],
            tracks_by_playlist={'mine': [], 'theirs': []},
            saved_tracks=[],
            user={'id': 'me', 'display_name': 'Test User'},
        )
        export_all_data(sp, str(tmp_path), my_playlists_only=True)

        with open(tmp_path / 'playlists.csv', newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        assert [r['id'] for r in rows] == ['mine']
