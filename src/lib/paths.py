"""lib.paths - resolve every root path the project touches.

single source of truth for ARCHIVE_PATH / TAPEDECK_PATH / PLAYLISTS_PATH /
FFMPEG_PATH. uppercase-only - the old dual-case (ARCHIVE_PATH / archive_path)
fallback has been dropped in favor of one canonical env var name per root.

config lives at the repo root: .env, and organize/config.yaml, sit next to
each other there. this module doesn't load .env itself - the calling cli.py
is responsible for calling dotenv.load_dotenv() once at startup, same as any
other environment setup.
"""

import os


def resolve(env_name, cli=None, default=None, required=False):
    """cli override > os.environ[env_name] > default.

    raises ValueError if required and nothing resolves. this is the one
    place the cli-arg-or-env-or-fallback pattern is implemented - every
    named resolver below is a thin call into this.
    """
    value = cli or os.getenv(env_name) or default
    if required and not value:
        raise ValueError(f"{env_name} not set - pass it explicitly or add it to .env")
    return value


def archive_path(cli=None):
    """the crate root - ARCHIVE_PATH."""
    return resolve('ARCHIVE_PATH', cli, default=os.path.expanduser('~/music/tapebuilding'))


def tapedeck_path(cli=None):
    """the rotation/sync destination - TAPEDECK_PATH."""
    return resolve('TAPEDECK_PATH', cli, default=os.path.expanduser('~/music/tapedeck'))


def playlists_path(cli=None):
    """where .m3u8s + exports live - PLAYLISTS_PATH. no fallback: a missing
    PLAYLISTS_PATH is a real configuration error, not something to guess at."""
    return resolve('PLAYLISTS_PATH', cli, required=True)


def exports_dir(playlists_path_value=None, cli=None):
    """PLAYLISTS_PATH/exports - spotify csvs + the cached catalog sidecar."""
    if cli:
        os.makedirs(cli, exist_ok=True)
        return cli
    base = playlists_path_value or playlists_path()
    exports = os.path.join(base, 'exports')
    os.makedirs(exports, exist_ok=True)
    return exports


def ffmpeg_path(cli=None):
    """ffmpeg executable, if not already on PATH - FFMPEG_PATH. no default:
    None means "let the tool find it on PATH itself"."""
    return resolve('FFMPEG_PATH', cli, required=False)
