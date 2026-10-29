"""lib.config - single source of truth for every environment variable the project reads.

loads the repo-root `.env` once at import time (python-dotenv never overrides
variables already present in the environment, so importing this from multiple
entry points is safe). every other module imports its settings from here
instead of calling `os.getenv()` / `os.environ` directly.

values are read lazily at attribute access, so `monkeypatch.setenv` in tests
still takes effect, and the cli-flag > env > default precedence is preserved by
the call sites (lib.paths.resolve() for path roots; the handlers in
core.process_unmatched, core.sync, and download.spotify_download for the rest).

precedence where a cli flag also exists: cli flag > env var > default.
lib.paths owns the cli-arg-or-env-or-default resolution for path roots
(ARCHIVE_PATH, TAPEDECK_PATH, PLAYLISTS_PATH, FFMPEG_PATH);
this module names every env var, its default, and how to parse it in one place,
including LIBRARY_CONFIG_PATH.
"""

import os

from dotenv import load_dotenv

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

_dotenv_path = os.path.join(_REPO_ROOT, ".env")
load_dotenv(_dotenv_path)  # override=False: existing environment always wins


def _as_bool(val):
    return val.lower() in ("true", "1", "yes", "on")


def _as_int(val):
    return int(val)  # raises ValueError on garbage, like the original int() calls


def _as_float(val):
    return float(val)


def _as_list(val):
    return [item.strip() for item in val.split(",") if item.strip()]


# every env var the project reads: name -> (parser, default)
# parser receives the raw string; None means "use the raw string".
# default of None means "unset / no override".
_SETTINGS = {
    # spotify - https://developer.spotify.com/dashboard
    "SPOTIFY_CLIENT_ID": (None, None),
    "SPOTIFY_CLIENT_SECRET": (None, None),
    "SPOTIFY_REDIRECT_URI": (None, "http://127.0.0.1:8888/callback"),
    "SPOTIFY_SP_DC": (None, None),
    "SPOTIFY_USER_ID": (None, None),
    # spotapi (spotify web-player graphql backend)
    "SPOTAPI_CACHE_DIR": (None, None),
    "SPOTAPI_NO_CACHE": (_as_bool, False),
    "SPOTAPI_DELAY": (_as_float, 0.15),
    # profile
    "SOUNDCLOUD_USER": (None, "me"),
    # paths - lib.paths.resolve() still owns cli > env > default precedence
    "ARCHIVE_PATH": (None, None),
    "TAPEDECK_PATH": (None, None),
    "PLAYLISTS_PATH": (None, None),
    "FFMPEG_PATH": (None, None),
    # library config (beets) - centralized path read by lib and organize
    "LIBRARY_CONFIG_PATH": (None, os.path.join(_REPO_ROOT, "library_config.yaml")),
    # download
    "DOWNLOAD_FORMAT": (None, "mp3"),
    "DOWNLOAD_QUALITY": (None, "320k"),
    "PLAYLISTS_EXCLUDE": (_as_list, []),
    "DOWNLOAD_PRE_SKIP_EXISTING": (_as_bool, None),
    "DOWNLOAD_COOKIES_FILE": (None, None),
    "DOWNLOAD_RETRIES": (_as_int, None),
    # soundbyte / firebase
    "FIREBASE_PROJECT_ID": (None, None),
    "FIREBASE_CREDENTIALS_PATH": (None, None),
}


def __getattr__(name):
    """lazy read: os.getenv(name) with the registered default/parser, so
    monkeypatch.setenv in tests takes effect on every access."""
    if name not in _SETTINGS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    parser, default = _SETTINGS[name]
    raw = os.getenv(name)
    if raw is None:
        return default
    if parser is None:
        return raw
    return parser(raw)


def get(name, default=None):
    """explicit read: os.getenv(name, default), no parsing."""
    return os.getenv(name, default)
