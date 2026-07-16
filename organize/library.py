import os
import re
import glob


def resolve_library_root():
    return os.getenv('ARCHIVE_PATH') or os.getenv('archive_path') \
        or os.path.expanduser('~/music/tapebuilding')


def resolve_tapedeck_root(cli=None):
    """tapedeck root, from --tapedeck-path or the dual-case TAPEDECK_PATH env, with
    the same ~/music/tapebuilding-style fallback as the crate resolve. the tapedeck is
    a rotation subset mirrored to devices via syncthing (see tapedeck/README.md)."""
    return cli or os.getenv('TAPEDECK_PATH') or os.getenv('tapedeck_path') \
        or os.path.expanduser('~/music/tapedeck')


def _normalize(s):
    s = s.lower()
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def build_library_index(library_root):
    """keys are normalized so they survive spotDL's filename sanitization -
    minor spacing/punctuation differences still match existing files."""
    index = set()
    extensions = ('*.mp3', '*.flac', '*.m4a', '*.opus', '*.ogg', '*.wav', '*.aac')
    for ext in extensions:
        for filepath in glob.glob(os.path.join(library_root, ext)):
            stem = os.path.splitext(os.path.basename(filepath))[0]
            index.add(_normalize(stem))
    return index


def scan_existing(library_root, candidate_names):
    """direct os.path.exists check; prefer scan_existing_fuzzy for normalized matching."""
    existing = 0
    new = 0
    for name in candidate_names:
        if name and os.path.exists(os.path.join(library_root, name)):
            existing += 1
        else:
            new += 1
    return existing, new


def scan_existing_fuzzy(candidate_names, library_index):
    existing = 0
    new = 0
    for name in candidate_names:
        stem = os.path.splitext(name)[0]
        if _normalize(stem) in library_index:
            existing += 1
        else:
            new += 1
    return existing, new
