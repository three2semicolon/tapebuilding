"""tests for lib.spotapi_client's pure mappers, against minimal fixtures that mirror
the real graphql response shapes (trimmed from actual probe dumps)."""

from lib import spotapi_client as c
import pytest

def _track_data(**over):
    d = {
        '__typename': 'Track', 'name': 'Magic Love', 'uri': 'spotify:track:1rEjbK9xDZI36YNN6n4NwO',
        'artists': {'items': [{'profile': {'name': 'Bent'}}, {'profile': {'name': 'Other'}}]},
        'albumOfTrack': {'name': 'The Everlasting Blink'},
        'trackDuration': {'totalMilliseconds': 268560}, 'contentRating': {'label': 'NONE'},
        'discNumber': 1, 'trackNumber': 9, 'playcount': '3563077',
    }
    d.update(over)
    return d


def test_playlist_item_maps_to_spotipy_shape():
    item = {'addedAt': {'isoString': '2023-12-18T16:53:24Z'},
            'addedBy': {'data': {'username': 'three2won'}},
            'itemV2': {'data': _track_data()}}
    m = c._map_playlist_item(item)
    assert m['track']['id'] == '1rEjbK9xDZI36YNN6n4NwO'
    assert [a['name'] for a in m['track']['artists']] == ['Bent', 'Other']
    assert m['track']['duration_ms'] == 268560
    assert m['track']['popularity'] == 3563077
    assert m['track']['external_urls']['spotify'].endswith('/track/1rEjbK9xDZI36YNN6n4NwO')
    assert m['added_by'] == {'id': 'three2won'} and m['added_at'] == '2023-12-18T16:53:24Z'


def test_non_track_items_are_skipped():
    assert c._map_playlist_item({'itemV2': {'data': {'__typename': 'Episode'}}}) is None
    assert c._map_playlist_item({'itemV2': {'__typename': 'NotFound'}}) is None
    assert c._map_saved_item({'track': {'data': {'__typename': 'Episode'}}}) is None


def test_saved_item_uses_wrapper_uri_and_has_no_added_by():
    data = _track_data(uri=None, contentRating={'label': 'EXPLICIT'})
    data.pop('uri')
    data.pop('trackDuration')
    data.pop('playcount')
    data['duration'] = {'totalMilliseconds': 193740}
    m = c._map_saved_item({'addedAt': {'isoString': '2026-10-04T19:04:43Z'},
                           'track': {'_uri': 'spotify:track:1CbxG199T0fzfUV5EO7aPV', 'data': data}})
    assert m['track']['id'] == '1CbxG199T0fzfUV5EO7aPV'
    assert m['track']['duration_ms'] == 193740
    assert m['track']['explicit'] is True
    assert m['track']['popularity'] == 0
    assert m['added_by'] is None


def test_local_track_has_empty_id_and_flag():
    t = c._map_track(_track_data(uri='spotify:local:artist:album:title:123'))
    assert t['id'] == '' and t['is_local'] is True and t['external_urls'] == {}


def test_library_filters_to_playlists_only():
    def wrap(typename, uri):
        return {'item': {'__typename': typename, '_uri': uri, 'data': {
            'name': 'x', 'ownerV2': {'data': {'username': 'me', 'name': 'Me'}}}}}
    items = [wrap('PlaylistResponseWrapper', 'spotify:playlist:abc'),
             wrap('ArtistResponseWrapper', 'spotify:artist:def'),
             wrap('AlbumResponseWrapper', 'spotify:album:ghi'),
             wrap('LibraryFolderResponseWrapper', 'spotify:user:me:folder:jkl'),
             wrap('LibraryPseudoPlaylistResponseWrapper', 'spotify:collection:tracks')]
    out = [m for m in map(c._map_library_playlist, items) if m]
    assert [p['id'] for p in out] == ['abc']
    assert out[0]['owner'] == {'id': 'me', 'display_name': 'Me'}
    assert out[0]['public'] is None


def test_playlist_meta_images_and_total():
    m = c._map_playlist_meta('spotify:playlist:abc', {
        'name': 'n', 'images': {'items': [{'sources': [{'url': 'u', 'width': None, 'height': None}]}]}}, 250)
    assert m['tracks']['total'] == 250 and m['images'][0]['url'] == 'u'


# --- soundbyte lookups. NOTE: these fixtures follow spotapi's source + the web player's
# --- usual shapes, not a captured dump; replace with a trimmed real dump once probed.

def test_plain_query_strips_official_api_field_filters():
    assert c._plain_query('album:"Mr. Wonderful" artist:"Action Bronson"') == 'Mr. Wonderful Action Bronson'
    assert c._plain_query('album:"x" y') == 'x y'
    assert c._plain_query('Mr. Wonderful Action Bronson') == 'Mr. Wonderful Action Bronson'


def test_search_album_item_maps_and_rejects_non_albums():
    item = {'data': {'__typename': 'Album', 'uri': 'spotify:album:7ijgeLAW3W3vZ9jf6tozFq', 'name': 'Mr. Wonderful',
                     'artists': {'items': [{'profile': {'name': 'Action Bronson'}}]}}}
    m = c._map_search_album(item)
    assert m['id'] == '7ijgeLAW3W3vZ9jf6tozFq' and m['name'] == 'Mr. Wonderful'
    assert m['external_urls']['spotify'] == 'https://open.spotify.com/album/7ijgeLAW3W3vZ9jf6tozFq'
    assert c._map_search_album({'data': {'uri': 'spotify:artist:abc'}}) is None


def test_album_track_item_maps_to_simplified_track():
    item = {'track': {'uri': 'spotify:track:6bj42Hzr3RErxhfgSTdSx6', 'name': 'Terry',
                      'artists': {'items': [{'profile': {'name': 'Action Bronson'}}]},
                      'duration': {'totalMilliseconds': 289492}, 'contentRating': {'label': 'EXPLICIT'},
                      'trackNumber': 3, 'discNumber': 1}}
    t = c._map_album_track_item(item)
    assert t['id'] == '6bj42Hzr3RErxhfgSTdSx6' and t['explicit'] is True and t['duration_ms'] == 289492
    assert c._map_album_track_item({'track': {}}) is None


# --- change detection / cache / resilience ----------------------------------------------


class _Stub(c.SpotApiClient):
    """no network: counts page fetches, serves canned playlist/liked pages."""

    def __init__(self, playlists, liked_items, dead=()):
        self._delay = 0
        self._fetch_track_counts = False
        self._snapshots = {}
        self.playlists, self.liked_items, self.dead = playlists, liked_items, set(dead)
        self.playlist_fetches = 0
        self.liked_fetches = 0

    def _playlist_page(self, playlist_id, limit, offset):
        if playlist_id in self.dead:
            raise c.PlaylistNotAccessible(f"playlist {playlist_id} not accessible (NotFound)")
        self.playlist_fetches += 1
        items = self.playlists[playlist_id][offset:offset + limit]
        return {'content': {'items': items, 'totalCount': len(self.playlists[playlist_id])}}

    def _saved_page(self, limit, offset):
        if limit > 1:
            self.liked_fetches += 1
        return {'items': self.liked_items[offset:offset + limit], 'totalCount': len(self.liked_items)}


def _pl_item(n):
    return {'addedAt': {'isoString': '2024-01-01T00:00:00Z'},
            'itemV2': {'data': _track_data(uri=f'spotify:track:t{n}', name=f'song {n}')}}


def _liked(n):
    d = _track_data()
    d.pop('uri')
    d.pop('trackDuration')
    d['duration'] = {'totalMilliseconds': 1}
    return {'addedAt': {'isoString': f'2026-01-{n:02d}T00:00:00Z'}, 'track': {'_uri': f'spotify:track:l{n}', 'data': d}}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('SPOTAPI_CACHE_DIR', str(tmp_path))
    monkeypatch.delenv('SPOTAPI_NO_CACHE', raising=False)
    return tmp_path


def test_playlist_tracks_cached_until_snapshot_changes(cache_dir):
    sp = _Stub({'p1': [_pl_item(1), _pl_item(2)]}, [])
    sp._snapshots['p1'] = 'rev1'
    assert len(sp.playlist_tracks('p1')['items']) == 2 and sp.playlist_fetches == 1
    assert len(sp.playlist_tracks('p1')['items']) == 2 and sp.playlist_fetches == 1   # cache hit
    sp._snapshots['p1'] = 'rev2'                                                       # playlist edited
    sp.playlists['p1'].append(_pl_item(3))
    assert len(sp.playlist_tracks('p1')['items']) == 3 and sp.playlist_fetches == 2


def test_cache_disabled_by_env(cache_dir, monkeypatch):
    monkeypatch.setenv('SPOTAPI_NO_CACHE', '1')
    sp = _Stub({'p1': [_pl_item(1)]}, [])
    sp._snapshots['p1'] = 'rev1'
    sp.playlist_tracks('p1')
    sp.playlist_tracks('p1')
    assert sp.playlist_fetches == 2


def test_no_snapshot_means_no_caching(cache_dir):
    sp = _Stub({'p1': [_pl_item(1)]}, [])
    sp.playlist_tracks('p1')
    sp.playlist_tracks('p1')
    assert sp.playlist_fetches == 2


def test_inaccessible_playlist_is_skipped_not_fatal(cache_dir):
    sp = _Stub({}, [], dead={'gone'})
    assert sp.playlist_tracks('gone') == {'items': [], 'next': None}


def test_liked_songs_cached_and_invalidated_by_new_like(cache_dir):
    liked = [_liked(3), _liked(2), _liked(1)]      # newest first, like spotify
    sp = _Stub({}, liked)
    assert len(sp.current_user_saved_tracks()['items']) == 3 and sp.liked_fetches == 1
    assert len(sp.current_user_saved_tracks()['items']) == 3 and sp.liked_fetches == 1   # cache hit
    sp.liked_items.insert(0, _liked(4))
    assert len(sp.current_user_saved_tracks()['items']) == 4 and sp.liked_fetches == 2
    sp.liked_items.pop()                                                                  # an unlike
    assert len(sp.current_user_saved_tracks()['items']) == 3 and sp.liked_fetches == 3


def test_stale_cache_entry_is_ignored(cache_dir, monkeypatch):
    c._cache_write('playlist_x', 'rev1', [{'a': 1}])
    assert c._cache_read('playlist_x', 'rev1') == [{'a': 1}]
    monkeypatch.setattr(c.time, 'time', lambda: 10**10)       # far future -> older than max age
    assert c._cache_read('playlist_x', 'rev1') is None


def test_library_entry_without_name_is_skipped_and_snapshot_mapped():
    stub = {'item': {'__typename': 'PlaylistResponseWrapper', '_uri': 'spotify:playlist:dead', 'data': {}}}
    assert c._map_library_playlist(stub) is None
    ok = {'item': {'__typename': 'PlaylistResponseWrapper', '_uri': 'spotify:playlist:abc',
                   'data': {'name': 'n', 'revisionId': 'AAAA'}}}
    assert c._map_library_playlist(ok)['snapshot_id'] == 'AAAA'
