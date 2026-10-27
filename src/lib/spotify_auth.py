"""lib.spotify_auth - the two spotify auth flows used across the project.

authenticate_user()   - user auth (playlists, liked songs). picks the backend from the
                         environment: SPOTIFY_SP_DC set -> lib.spotapi_client (spotapi,
                         no premium needed); otherwise the official web api via OAuth
                         (authenticate_user_oauth(), needs premium on the app owner's
                         account now). both return a spotipy-shaped client.
                         was download.spotify_utils.authenticate_spotify().
authenticate_client()  - client-credentials auth (public search, no login -
                         used for the soundbyte album/track lookup). was
                         download.soundbyte_albums._get_spotify_token()'s
                         hand-rolled requests calls, now on spotipy so
                         call sites use the same sp.search()/sp.album(...)
                         interface as the user-auth flow.

does not call load_dotenv() itself - the calling cli.py loads .env once at
startup, same as any other environment setup.
"""

import os

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth

SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:8888/callback')


def _token_cache_path():
    """anchor the token cache to the repo root (next to .env), not whatever
    the process's cwd happens to be - the old bare 'token_cache' relative
    path landed wherever the process was invoked from."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(repo_root, '.spotify_token_cache')


def _require_credentials():
    if not all([SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET]):
        raise ValueError(
            "SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET not set - add them to .env"
        )


def authenticate_user():
    """user-auth flow: playlist reads, liked songs. spotapi (sp_dc cookie) when
    SPOTIFY_SP_DC is set, official-api oauth otherwise. read at call time, not import
    time, so it works regardless of when .env was loaded."""
    if os.getenv('SPOTIFY_SP_DC'):
        from lib.spotapi_client import connect   # lazy: spotapi stays optional for oauth-only setups
        return connect()
    return authenticate_user_oauth()


def authenticate_user_oauth():
    """official web api oauth flow: playlist reads, liked songs, follows."""
    _require_credentials()
    scope = "playlist-read-private playlist-read-collaborative user-library-read user-follow-read"
    auth_manager = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=scope,
        cache_path=_token_cache_path(),
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def authenticate_client():
    """public catalog lookups (album search, album tracks) for download.soundbyte.
    spotapi (sp_dc cookie) when SPOTIFY_SP_DC is set - same client as
    authenticate_user(), which also implements search()/album() - otherwise the
    official client-credentials flow."""
    if os.getenv('SPOTIFY_SP_DC'):
        from lib.spotapi_client import connect
        return connect(fetch_track_counts=False)
    return authenticate_client_oauth()


def authenticate_client_oauth():
    """official client-credentials flow: public search, no user login."""
    _require_credentials()
    auth_manager = SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    )
    return spotipy.Spotify(auth_manager=auth_manager)
