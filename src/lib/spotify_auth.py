"""lib.spotify_auth - the two spotify auth flows used across the project.

authenticate_user()   - OAuth user auth (playlists, liked songs, follows).
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
    """user-auth flow: playlist reads, liked songs, follows."""
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
    """client-credentials flow: public search (album/track lookup), no
    user login required. used by download.soundbyte - see its module docs
    for the sp.search()-based call sites this replaces."""
    _require_credentials()
    auth_manager = SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    )
    return spotipy.Spotify(auth_manager=auth_manager)
