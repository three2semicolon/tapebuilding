import re

# organize/normalize_artists.py
#
# beets plugin: normalizes artist strings before they're used in path templates.
# install: add 'normalize_artists' to plugins in config.yaml and set pluginpath
#          to the organize/ directory.
#
# the pure function normalize_artist() is importable (and unit-testable)
# without beets installed - only the BeetsPlugin subclass needs beets.
try:
    from beets.plugins import BeetsPlugin
except ImportError:  # pragma: no cover - lets tests import normalize_artist()
    class BeetsPlugin:  # minimal stand-in
        def __init__(self, *a, **k):
            pass

        def register_listener(self, *a, **k):
            pass

# featuring aliases -> normalized to "feat."
#
# BUGFIX_PLAN.md Bug 13: the old pattern had no word boundaries and was
# applied with .search(), so it matched "ft"/"f."/"feat" INSIDE words -
# "Daft Punk" -> "Da feat. Punk", "Soft Cell" -> "So feat. Cell". The marker
# must now be a whole token: (?<!\w) before it, and \b after the word forms
# ("f." keeps its dot as the terminator). An optional opening bracket and
# surrounding whitespace are still consumed, as before.
_FEAT_RE = re.compile(
    r'\s*[\(\[]?\s*(?<!\w)(?:feat(?:uring)?\b\.?|ft\b\.?|f\.)\s*',
    re.IGNORECASE,
)

# collab "x" between artists - whitespace-delimited only. (Old pattern was a
# bare \b[xX]\b applied to the featuring part, which turned a lone "X" in a
# name - "Malcolm X" - into a separator.)
_COLLAB_X_RE = re.compile(r'\s+[xX]\s+')

# " and " as an artist separator
_AND_WORD_RE = re.compile(r'\s+and\s+', re.IGNORECASE)

_SPACES_RE = re.compile(r'  +')
_EDGE_PUNCT_RE = re.compile(r'^[\s,&]+|[\s,&]+$')


def _normalize_list(artists):
    """join a list of artists with ", " (D8 - was "A & B" / "A, B & C").
    a single artist is returned as-is."""
    artists = [a.strip() for a in artists if a.strip()]
    return ', '.join(artists)


def normalize_artist(raw):
    """Canonicalise an artist string for use in file paths."""
    # Strip whitespace; if nothing remains, return empty string
    if not raw or not raw.strip():
        return ''

    # Split off a featuring clause first - it is handled separately below.
    # A match at the very start of the string (nothing before it) isn't a
    # featuring credit, it's the artist's name ("Ft. Lauderdale") - leave it.
    feat_match = _FEAT_RE.search(raw)
    if feat_match and raw[:feat_match.start()].strip():
        main_part = raw[:feat_match.start()].strip()
        feat_part = raw[feat_match.end():].strip().strip('()[] ')
        # If the featuring part only contained punctuation, treat it as a plain "feat."
        if not feat_part:
            feat_part = 'feat.'
    else:
        main_part = raw
        feat_part = None

    # Normalise "x" / "and" collaborations to a comma list
    main_part = _COLLAB_X_RE.sub(', ', main_part)
    main_part = _AND_WORD_RE.sub(', ', main_part)

    # Split on commas, strip each piece, drop empties
    main_artists = [a.strip() for a in main_part.split(',') if a.strip()]
    result = _normalize_list(main_artists)

    if feat_part:
        # Normalise the featuring part the same way
        feat_part = _COLLAB_X_RE.sub(', ', feat_part)
        feat_part = _AND_WORD_RE.sub(', ', feat_part)
        feat_artists = [a.strip() for a in feat_part.split(',') if a.strip()]
        feat_str = _normalize_list(feat_artists)
        if feat_str == "feat.":
            result = f"{result} feat."
        else:
            result = f"{result} feat. {feat_str}"

    # Clean up spacing and edge punctuation
    result = _SPACES_RE.sub(' ', result)
    result = _EDGE_PUNCT_RE.sub('', result)
    return result


class NormalizeArtistsPlugin(BeetsPlugin):

    def __init__(self):
        super().__init__()
        self.register_listener('import_task_choice', self.on_import_task_choice)
        self.register_listener('album_imported', self.on_album_imported)
        self.register_listener('item_imported', self.on_item_imported)

    def _normalize_item(self, item):
        changed = False
        for field in ('artist', 'albumartist'):
            raw = getattr(item, field, None)
            if raw:
                normalized = normalize_artist(raw)
                if normalized != raw:
                    setattr(item, field, normalized)
                    changed = True
        return changed

    def on_import_task_choice(self, session, task):
        # normalize before the path template is applied
        if task.is_album:
            for item in task.items or []:
                self._normalize_item(item)
        elif hasattr(task, 'item') and task.item:
            self._normalize_item(task.item)

    def on_album_imported(self, lib, album):
        raw = album.albumartist
        if raw:
            normalized = normalize_artist(raw)
            if normalized != raw:
                album.albumartist = normalized
                album.store()

    def on_item_imported(self, lib, item):
        changed = self._normalize_item(item)
        if changed:
            item.store()
