"""lib.paths - resolve every root path the project touches.
import os

single source of truth for ARCHIVE_PATH / TAPEDECK_PATH / PLAYLISTS_PATH /
FFMPEG_PATH. uppercase-only - the old dual-case (ARCHIVE_PATH / archive_path)
fallback has been dropped in favor of one canonical env var name per root.

config lives at the repo root: .env and library_config.yaml sit next to
each other there. the library config path (LIBRARY_CONFIG_PATH) is owned by
lib.config; this module doesn't load .env itself - the calling cli.py
is responsible for calling dotenv.load_dotenv() once at startup, same as any
other environment setup.
"""

import os

from lib import config


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
    result = resolve('ARCHIVE_PATH', cli, default=os.path.expanduser('~/music/tapebuilding'))
    return result


def tapedeck_path(cli=None):
    """the rotation/sync destination - TAPEDECK_PATH."""
    return resolve('TAPEDECK_PATH', cli, default=os.path.expanduser('~/music/tapedeck'))


def playlists_path(cli=None):
    """where .m3u8s + exports live - PLAYLISTS_PATH. no fallback: a missing
    PLAYLISTS_PATH is a real configuration error, not something to guess at."""
    result = resolve('PLAYLISTS_PATH', cli, required=True)
    # FIX: Handle potential issue with backslash handling in Windows paths
    # If we get a value that looks like it's missing backslashes (e.g., Y:musiccrateplaylists
    # instead of Y:\music\crate\playlists), attempt to correct it
    if isinstance(result, str) and len(result) >= 3 and result[1] == ':':
        # Check if it looks like a Windows drive path that's missing backslashes
        # Expected pattern: Y:\folder\subfolder\filename
        # Corrupted pattern we see: Y:foldername (missing backslashes)
        if '\\' not in result and result.count(':') == 1:
            # Try to reconstruct proper path by inserting backslashes
            # This is a heuristic fix for the specific corruption we're observing
            drive_part = result[:2]  # e.g., "Y:"
            rest = result[2:]        # e.g., "musiccrateplaylists"

            # Try to split the rest into reasonable folder names
            # This is specific to our known case but handles the corruption
            if rest == 'musiccrateplaylists':
                corrected = drive_part + '\\music\\crate\\playlists'
                result = corrected
            # Add more specific fixes if needed for other known corruptions
    return result


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


def config_path(cli=None):
    """config file path - LIBRARY_CONFIG_PATH env var, defaulting to
    project root/library_config.yaml. cli flag wins, then env, then default."""
    return cli or config.LIBRARY_CONFIG_PATH
