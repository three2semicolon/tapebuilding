"""lib.spotapi_client - a spotipy-shaped client backed by SpotAPI (spotify's web-player
graphql), for when the official web api is off the table (it now requires premium).

the point of this module is that nothing downstream has to change: it exposes the
handful of spotipy methods download.spotify.spotify_api / spotify_export and
playlists.build actually call, and returns dicts in spotipy's shape -

    current_user()                      -> {'id', 'display_name'}
    current_user_playlists(limit=...)   -> {'items': [playlist...], 'next': None}
    playlist(id, fields=None)           -> playlist (with tracks.total, images)
    playlist_tracks(id, limit=...)      -> {'items': [{'track', 'added_at', 'added_by'}], 'next': None}
    current_user_saved_tracks(limit=..) -> same item shape as playlist_tracks
    next(result)                        -> None (everything is paged eagerly, 'next' is always None)

and, for download.soundbyte (public catalog lookups, same client):

    search(q, type='album', limit=5)    -> {'albums': {'items': [{'id','name','artists','external_urls'}]}}
    album(id)                           -> {'name', 'tracks': {'items': [simplified track...], 'next': None}}

so `while results: ... if results.get('next'): results = sp.next(results)` loops in
the callers run exactly once with the full result.

auth is the browser's `sp_dc` cookie (SPOTIFY_SP_DC), not oauth - no client id/secret,
no captcha solver. treat that cookie like a password.

what spotapi's graphql doesn't have, and what we do about it:
  - popularity (0-100): not exposed. playlist items do carry a `playcount`, which is
    put in the 'popularity' slot instead, so merge_and_deduplicate's "keep the more
    popular" tiebreak still has something to compare. NOTE the csv column is now a raw
    play count, not 0-100. liked-songs items have no playcount -> 0 (ties keep first seen).
  - playlist `public` flag: not exposed -> None (blank in the csv).
  - track count per playlist: not in the library listing. sp.playlist() fills it in; the
    bulk listing leaves it 0 unless fetch_track_counts=True (one extra request per playlist).
  - added_by on liked songs: n/a -> None, same as spotipy.

speed: one BaseClient (via PrivatePlaylist) serves every request. spotapi's PublicPlaylist/
PublicAlbum/Song each build their own BaseClient, and a fresh BaseClient re-downloads the
open.spotify.com page + the web-player js bundle to find query hashes before its first
request - doing that per playlist is what made the first version crawl (and 504). so
fetchPlaylist is issued through the shared client here instead.

change detection: playlists carry a revisionId (exposed as spotipy's 'snapshot_id') in
the library listing, and liked songs have (total, newest uri, newest added_at). tracks are
cached on disk keyed on those, so a re-run only refetches what actually changed - this is
what keeps `core sync` / `process-unmatched` cheap. cache lives in SPOTAPI_CACHE_DIR
(default <repo>/.spotapi_cache; gitignore it); entries also expire after 14 days, and
SPOTAPI_NO_CACHE=1 forces a full refetch.

this talks to unofficial endpoints and can break whenever spotify changes the web
player. everything spotapi-specific lives in this one file on purpose.
"""

import json
import os
import re
import time
from collections.abc import Mapping

from spotapi import Config, Login, NoopLogger, PrivatePlaylist

_PATHFINDER = "https://api-partner.spotify.com/pathfinder/v1/query"
_PAGE = 343          # spotapi's own upper limit for playlist / liked-songs pages
_LIBRARY_PAGE = 50


_CACHE_MAX_AGE = 14 * 86400


class SpotApiError(RuntimeError):
    pass


class PlaylistNotAccessible(SpotApiError):
    pass


# --- on-disk cache (keyed on a change fingerprint) ----------------------------------

def _cache_dir():
    return os.environ.get('SPOTAPI_CACHE_DIR') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.spotapi_cache')


def _cache_enabled():
    return not os.environ.get('SPOTAPI_NO_CACHE')


def _cache_read(name, fingerprint):
    """cached items for `name` if the stored fingerprint matches and the entry is fresh, else None."""
    if not _cache_enabled():
        return None
    try:
        with open(os.path.join(_cache_dir(), name + '.json'), encoding='utf-8') as f:
            blob = json.load(f)
    except (OSError, ValueError):
        return None
    if blob.get('fingerprint') != fingerprint or time.time() - blob.get('saved_at', 0) > _CACHE_MAX_AGE:
        return None
    return blob.get('items')


def _cache_write(name, fingerprint, items):
    if not _cache_enabled():
        return
    path = os.path.join(_cache_dir(), name + '.json')
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + '.tmp', 'w', encoding='utf-8') as f:
            json.dump({'fingerprint': fingerprint, 'saved_at': time.time(), 'items': items}, f)
        os.replace(path + '.tmp', path)
    except OSError as e:
        print(f"  warning: could not write spotapi cache {path}: {e}")


# --- pure mappers (no network; unit-tested against real response dumps) -----------

def _uri_id(uri):
    return uri.rsplit(':', 1)[-1] if uri else ''


def _map_track(data, uri=None):
    """graphql Track data -> spotipy track dict. handles both shapes seen in the dumps:
    liked songs (uri on the wrapper as _uri, duration under 'duration') and playlist
    items (uri in data, duration under 'trackDuration')."""
    uri = uri or data.get('uri') or ''
    is_local = uri.startswith('spotify:local:')
    track_id = '' if is_local else _uri_id(uri)
    duration = data.get('trackDuration') or data.get('duration') or {}
    album = data.get('albumOfTrack') or {}
    artist_items = (data.get('artists') or {}).get('items') or []
    try:
        popularity = int(data.get('playcount') or 0)
    except (TypeError, ValueError):
        popularity = 0
    return {
        'id': track_id,
        'name': data.get('name') or '',
        'artists': [{'name': (a.get('profile') or {}).get('name') or ''} for a in artist_items],
        'album': {'name': album.get('name') or ''},
        'duration_ms': duration.get('totalMilliseconds') or 0,
        'explicit': (data.get('contentRating') or {}).get('label') == 'EXPLICIT',
        'popularity': popularity,
        'external_urls': {'spotify': f'https://open.spotify.com/track/{track_id}'} if track_id else {},
        'track_number': data.get('trackNumber') or 0,
        'disc_number': data.get('discNumber') or 0,
        'is_local': is_local,
    }


def _map_playlist_item(item):
    """one entry of playlistV2.content.items -> spotipy playlist-track item, or None for
    anything that isn't a plain Track (episodes, removed/unavailable entries)."""
    data = (item.get('itemV2') or {}).get('data') or {}
    if data.get('__typename') != 'Track':
        return None
    added_by = ((item.get('addedBy') or {}).get('data') or {}).get('username')
    return {
        'track': _map_track(data),
        'added_at': (item.get('addedAt') or {}).get('isoString') or '',
        'added_by': {'id': added_by} if added_by else None,
    }


def _map_saved_item(item):
    """one entry of me.library.tracks.items -> spotipy saved-track item, or None."""
    wrapper = item.get('track') or {}
    data = wrapper.get('data') or {}
    if data.get('__typename') != 'Track':
        return None
    return {
        'track': _map_track(data, wrapper.get('_uri')),
        'added_at': (item.get('addedAt') or {}).get('isoString') or '',
        'added_by': None,
    }


def _map_playlist_meta(uri, data, track_total=0):
    """playlist graphql data (library item or playlistV2) -> spotipy playlist dict."""
    owner = (data.get('ownerV2') or {}).get('data') or {}
    playlist_id = _uri_id(uri)
    images = []
    for image in (data.get('images') or {}).get('items') or []:
        for src in image.get('sources') or []:
            images.append({'url': src.get('url'), 'width': src.get('width'), 'height': src.get('height')})
    return {
        'id': playlist_id,
        'name': data.get('name') or '',
        'description': data.get('description') or '',
        'owner': {'id': owner.get('username') or '', 'display_name': owner.get('name') or ''},
        'public': None,
        'snapshot_id': data.get('revisionId') or '',
        'tracks': {'total': track_total},
        'external_urls': {'spotify': f'https://open.spotify.com/playlist/{playlist_id}'},
        'images': images,
    }


def _map_library_playlist(item):
    """one libraryV3 item -> playlist dict, or None for artists/albums/folders/podcasts
    and the liked-songs pseudo-playlist."""
    wrapper = item.get('item') or {}
    if wrapper.get('__typename') != 'PlaylistResponseWrapper':
        return None
    data = wrapper.get('data') or {}
    if not data.get('name'):
        return None   # removed / unavailable entries come back as stubs with no name
    return _map_playlist_meta(wrapper.get('_uri') or data.get('uri') or '', data)


def _plain_query(q):
    """spotify's web player search has no field filters, so `album:"x" artist:"y"` (the
    official api's syntax, which soundbyte builds) would be matched as literal text.
    strip the field prefixes and quotes down to plain search terms."""
    q = re.sub(r'\b(?:album|artist|track|year):', ' ', q)
    return re.sub(r'\s+', ' ', q.replace('"', ' ')).strip()


def _map_search_album(item):
    """one searchV2.albumsV2 item -> spotipy simplified-album dict, or None."""
    data = item.get('data') or item
    uri = data.get('uri') or item.get('_uri') or ''
    if not uri.startswith('spotify:album:'):
        return None
    album_id = _uri_id(uri)
    return {
        'id': album_id,
        'name': data.get('name') or '',
        'artists': [{'name': (a.get('profile') or {}).get('name') or ''}
                    for a in (data.get('artists') or {}).get('items') or []],
        'external_urls': {'spotify': f'https://open.spotify.com/album/{album_id}'},
    }


def _map_album_track_item(item):
    """one albumUnion.tracksV2 item -> spotipy simplified-track dict, or None."""
    data = item.get('track') or {}
    if not data.get('uri'):
        return None
    return _map_track(data)


# --- client -----------------------------------------------------------------------

class SpotApiClient:
    def __init__(self, login, user_id=None, delay=0.15, fetch_track_counts=False):
        self._login = login
        self._priv = PrivatePlaylist(login)    # the one BaseClient everything below shares
        self._user_id = user_id
        self._delay = delay
        self._fetch_track_counts = fetch_track_counts
        self._snapshots = {}                   # playlist id -> revisionId, filled by listing / playlist()

    def _retry(self, fn, *args, **kwargs):
        """3 attempts with backoff: the unofficial endpoints throw the occasional 5xx."""
        for attempt in range(3):
            try:
                return fn(*args, **kwargs)
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)

    def _sleep(self):
        if self._delay:
            time.sleep(self._delay)

    def _query(self, operation, variables):
        """one persisted graphql query via the logged-in client (same call spotapi's own
        PrivatePlaylist makes; used directly for libraryV3 because get_library() has no
        offset and no folder flattening)."""
        params = {
            "operationName": operation,
            "variables": json.dumps(variables),
            "extensions": json.dumps({"persistedQuery": {
                "version": 1, "sha256Hash": self._priv.base.part_hash(operation)}}),
        }
        def once():
            resp = self._login.client.post(_PATHFINDER, params=params, authenticate=True)
            if resp.fail:
                raise SpotApiError(f"{operation} failed: {resp.error.string}")
            if not isinstance(resp.response, Mapping):
                raise SpotApiError(f"{operation}: invalid json")
            return resp.response
        return self._retry(once)

    def _playlist_page(self, playlist_id, limit, offset):
        # same query PublicPlaylist.get_playlist_info makes, but through the shared client
        info = self._query("fetchPlaylist", {
            "uri": f"spotify:playlist:{playlist_id}", "offset": offset, "limit": limit,
            "enableWatchFeedEntrypoint": False,
        })
        pl = (info.get('data') or {}).get('playlistV2') or {}
        if 'content' not in pl:
            raise PlaylistNotAccessible(f"playlist {playlist_id} not accessible ({pl.get('__typename', 'no data')})")
        return pl

    # -- spotipy surface ---------------------------------------------------------

    def current_user(self):
        user_id = self._user_id or self._priv.user.username
        return {'id': user_id, 'display_name': user_id}

    def current_user_playlists(self, limit=50):
        playlists, offset, total = [], 0, None
        while total is None or offset < total:
            lib = self._query("libraryV3", {
                "filters": [], "order": None, "textFilter": "",
                "features": ["LIKED_SONGS", "YOUR_EPISODES", "PRERELEASES"],
                "limit": _LIBRARY_PAGE, "offset": offset, "flatten": True,
                "expandedFolders": [], "folderUri": None, "includeFoldersWhenFlattening": True,
            })["data"]["me"]["libraryV3"]
            items = lib.get("items") or []
            total = lib.get("totalCount", 0)
            for item in items:
                mapped = _map_library_playlist(item)
                if mapped:
                    playlists.append(mapped)
                    self._snapshots[mapped['id']] = mapped['snapshot_id']
            if not items:
                break
            offset += len(items)
            self._sleep()

        if self._fetch_track_counts:
            for pl in playlists:
                try:
                    pl['tracks']['total'] = self._playlist_page(pl['id'], 1, 0)['content'].get('totalCount', 0)
                except PlaylistNotAccessible:
                    pass
                except Exception as e:
                    print(f"  warning: could not get track count for {pl['name']}: {e}")
                self._sleep()
        return {'items': playlists, 'next': None}

    def playlist(self, playlist_id, fields=None):
        pl = self._playlist_page(playlist_id, 1, 0)
        self._snapshots[playlist_id] = pl.get('revisionId') or ''
        return _map_playlist_meta(pl.get('uri') or f'spotify:playlist:{playlist_id}', pl,
                                  track_total=pl['content'].get('totalCount', 0))

    def playlist_tracks(self, playlist_id, limit=100):
        snapshot = self._snapshots.get(playlist_id)
        if snapshot:
            cached = _cache_read('playlist_' + playlist_id, snapshot)
            if cached is not None:
                return {'items': cached, 'next': None}

        items, offset, total = [], 0, None
        try:
            while total is None or offset < total:
                content = self._playlist_page(playlist_id, _PAGE, offset)['content']
                raw = content.get('items') or []
                total = content.get('totalCount', 0)
                items.extend(m for m in map(_map_playlist_item, raw) if m)
                if not raw:
                    break
                offset += len(raw)
                self._sleep()
        except PlaylistNotAccessible as e:
            # one dead/followed-and-removed playlist shouldn't abort a whole export
            print(f"  warning: skipping {e}")
            return {'items': [], 'next': None}

        if snapshot:
            _cache_write('playlist_' + playlist_id, snapshot, items)
        return {'items': items, 'next': None}

    def _saved_page(self, limit, offset):
        return self._retry(self._priv.get_saved_tracks_info, limit=limit, offset=offset)["data"]["me"]["library"]["tracks"]

    def current_user_saved_tracks(self, limit=50):
        # fingerprint = (total, newest uri, newest added_at): a like adds to the front and
        # changes the total, an unlike changes the total, so any edit moves one of the three.
        head = self._saved_page(1, 0)
        first = (head.get('items') or [{}])[0]
        fingerprint = [head.get('totalCount', 0), (first.get('track') or {}).get('_uri'),
                       (first.get('addedAt') or {}).get('isoString')]
        cached = _cache_read('liked_songs', fingerprint)
        if cached is not None:
            return {'items': cached, 'next': None}

        items, offset, total = [], 0, None
        while total is None or offset < total:
            tracks = self._saved_page(_PAGE, offset)
            raw = tracks.get('items') or []
            total = tracks.get('totalCount', 0)
            items.extend(m for m in map(_map_saved_item, raw) if m)
            if not raw:
                break
            offset += len(raw)
            self._sleep()
        _cache_write('liked_songs', fingerprint, items)
        return {'items': items, 'next': None}

    def next(self, result):
        return None

    # -- public catalog lookups (soundbyte) --------------------------------------

    def search(self, q, type='album', limit=5, **_):
        """album search only (that's all soundbyte uses). repeated queries are cached:
        soundbyte's three 'progressively looser' queries collapse to the same plain
        terms here, so a miss shouldn't cost three identical requests."""
        if type != 'album':
            raise NotImplementedError("SpotApiClient.search only supports type='album'")
        terms = _plain_query(q)
        cache = self.__dict__.setdefault('_search_cache', {})
        if (terms, limit) not in cache:
            resp = self._query("searchDesktop", {
                "searchTerm": terms, "offset": 0, "limit": limit, "numberOfTopResults": 5,
                "includeAudiobooks": False, "includeArtistHasConcertsField": False,
                "includePreReleases": True, "includeLocalConcertsField": False,
            })
            raw = (((resp.get('data') or {}).get('searchV2') or {}).get('albumsV2') or {}).get('items') or []
            cache[(terms, limit)] = [m for m in map(_map_search_album, raw) if m][:limit]
        return {'albums': {'items': cache[(terms, limit)]}}

    def album(self, album_id):
        items, offset, total, name = [], 0, None, ''
        while total is None or offset < total:
            union = (self._query("getAlbum", {
                "locale": "", "uri": f"spotify:album:{album_id}", "offset": offset, "limit": _PAGE,
            }).get('data') or {}).get('albumUnion') or {}
            if 'tracksV2' not in union:
                raise SpotApiError(f"album {album_id} not accessible ({union.get('__typename', 'no data')})")
            name = union.get('name') or name
            raw = union['tracksV2'].get('items') or []
            total = union['tracksV2'].get('totalCount', 0)
            items.extend(m for m in map(_map_album_track_item, raw) if m)
            if not raw:
                break
            offset += len(raw)
            self._sleep()
        return {'name': name, 'tracks': {'items': items, 'next': None}}


def connect(sp_dc=None, user_id=None, delay=None, fetch_track_counts=False):
    """build a logged-in SpotApiClient from the sp_dc browser cookie."""
    sp_dc = (sp_dc or os.environ.get('SPOTIFY_SP_DC') or '').strip().strip('"').strip("'")
    if not sp_dc:
        raise ValueError("SPOTIFY_SP_DC not set - copy the sp_dc cookie from open.spotify.com into .env")
    user_id = user_id or os.environ.get('SPOTIFY_USER_ID') or None
    if delay is None:
        delay = float(os.environ.get('SPOTAPI_DELAY', 0.15))
    cfg = Config(logger=NoopLogger())   # no captcha solver needed on the cookie path
    # cookies go in as a dict: Login.from_cookies' string parser truncates values containing '='
    login = Login.from_cookies({"identifier": user_id or "tapebuilding", "cookies": {"sp_dc": sp_dc}}, cfg)
    return SpotApiClient(login, user_id=user_id, delay=delay, fetch_track_counts=fetch_track_counts)


if __name__ == '__main__':
    # live smoke test: python -m lib.spotapi_client   (reads .env)
    from dotenv import load_dotenv
    load_dotenv()
    sp = connect(fetch_track_counts=False)
    print("user:", sp.current_user()['id'])
    pls = sp.current_user_playlists()['items']
    print(f"playlists: {len(pls)}")
    for p in pls[:5]:
        print(f"  {p['name']!r} owner={p['owner']['id']} id={p['id']}")
    print("liked songs total:", sp._saved_page(1, 0)["totalCount"])
    if pls:
        t = sp.playlist_tracks(pls[0]['id'])['items']
        print(f"first playlist: {len(t)} tracks; sample: {t[0]['track']['name'] if t else None}")
    # soundbyte path: album search + album tracks (these two response shapes are from
    # spotapi's source / memory of the web player, not from a captured dump - if the
    # output below is empty or blank-named, the mappers need adjusting)
    hits = sp.search('album:"Mr. Wonderful" artist:"Action Bronson"', type='album', limit=5)['albums']['items']
    print(f"album search: {len(hits)} hits; top: {hits[0] if hits else None}")
    if hits:
        a = sp.album(hits[0]['id'])
        print(f"album {a['name']!r}: {len(a['tracks']['items'])} tracks; sample: {a['tracks']['items'][:1]}")
