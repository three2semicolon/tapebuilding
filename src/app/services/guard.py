"""app.services.guard - path and name confinement for the web app.

Every route that takes a filesystem path or playlist name runs it through
these helpers so nothing ever escapes the crate root or the playlists
folder. All checks are lexical (no disk calls) except the final ``isfile``
probe in :func:`resolve_in`, which is only used when we genuinely need to
serve or read an existing file.
"""
import os
from urllib.parse import unquote

from lib.paths import archive_path, playlists_path


def crate_root():
    """Return the archive path made absolute and normalised.

    Raises :class:`ValueError` if ``ARCHIVE_PATH`` is empty or unset, so a
    missing ``.env`` never silently scans ``~/music/tapebuilding``.
    """
    root = archive_path()
    if not root:
        raise ValueError("ARCHIVE_PATH is not set")
    return os.path.normpath(os.path.abspath(os.path.expanduser(root)))


def crate_playlists_dir():
    """Return the playlists directory, raising if ``PLAYLISTS_PATH`` is unset."""
    return playlists_path()


def confine(root, p):
    """Resolve ``p`` against ``root`` and return the absolute path if it
    stays inside ``root``, else ``None``. Does not require the path to
    exist (useful for creating new files)."""
    root = os.path.realpath(root)
    segments = [unquote(seg) for seg in str(p).split("/") if seg not in ("", ".", "..")]
    if not segments:
        return None
    candidate = os.path.realpath(os.path.join(root, *segments))
    try:
        inside = os.path.commonpath([candidate, root]) == root
    except ValueError:
        inside = False
    if not inside:
        return None
    return candidate


def resolve_in(root, p):
    """Confine ``p`` to ``root`` and return the absolute path only if it is
    an existing file inside ``root``, else ``None``."""
    candidate = confine(root, p)
    if candidate is None or not os.path.isfile(candidate):
        return None
    return candidate


def safe_playlist_name(name):
    """Validate a playlist name: non-empty, no separators, not ``.``/``..``."""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return None
    return name
