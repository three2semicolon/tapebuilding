# organize/normalize_artists.py
#
# beets plugin: normalizes artist strings before they're used in path templates.
# install: add 'normalize_artists' to plugins in config.yaml and set pluginpath
#          to the organize/ directory.

import re
from beets.plugins import BeetsPlugin
from beets import ui


# featuring aliases → normalized to "feat."
_FEAT_RE = re.compile(
    r'\s*[\(\[]?\s*(?:feat(?:uring)?\.?|ft\.?|f\.)\s*',
    re.IGNORECASE
)

# collab "x" between artists - word boundaries so " x " matches but "xx"/"xo" don't
_COLLAB_X_RE = re.compile(r'(?<!\w)\s+[xX]\s+(?!\w)')

# " and " as an artist separator
_AND_WORD_RE = re.compile(r'\s+and\s+', re.IGNORECASE)

_SPACES_RE = re.compile(r'  +')
_EDGE_PUNCT_RE = re.compile(r'^[\s,&]+|[\s,&]+$')


def _normalize_list(artists):
    """single → "Artist"; two → "A & B"; three+ → "A, B & C"."""
    artists = [a.strip() for a in artists if a.strip()]
    if not artists:
        return ''
    if len(artists) == 1:
        return artists[0]
    if len(artists) == 2:
        return f"{artists[0]} & {artists[1]}"
    return ', '.join(artists[:-1]) + ' & ' + artists[-1]


def normalize_artist(raw):
    if not raw or not raw.strip():
        return raw

    # split off the featuring clause first - it's handled separately below
    feat_match = _FEAT_RE.search(raw)
    if feat_match:
        main_part = raw[:feat_match.start()].strip()
        feat_part = raw[feat_match.end():].strip().strip('()')
    else:
        main_part = raw
        feat_part = None

    main_part = _COLLAB_X_RE.sub(', ', main_part)
    main_part = _AND_WORD_RE.sub(', ', main_part)

    main_artists = [a.strip() for a in main_part.split(',') if a.strip()]
    result = _normalize_list(main_artists)

    if feat_part:
        feat_part = _COLLAB_X_RE.sub(', ', feat_part)
        feat_part = _AND_WORD_RE.sub(', ', feat_part)
        feat_artists = [a.strip() for a in feat_part.split(',') if a.strip()]
        feat_str = _normalize_list(feat_artists)
        result = f"{result} feat. {feat_str}"

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


if __name__ == '__main__':
    cases = [
        ("2Pac, Dr. Dre", "2Pac & Dr. Dre"),
        ("Joey Bada$$, Kirk Knight, Nyck Caution", "Joey Bada$$, Kirk Knight & Nyck Caution"),
        ("Kendrick Lamar feat. SZA", "Kendrick Lamar feat. SZA"),
        ("Drake ft. Future", "Drake feat. Future"),
        ("Tyler, the Creator", "Tyler, the Creator"),
        ("Mike & Keys", "Mike & Keys"),
        ("Smino x Saba", "Smino & Saba"),
        ("artist and artist", "artist & artist"),
        ("Flying Lotus featuring Kendrick Lamar", "Flying Lotus feat. Kendrick Lamar"),
        ("a, b, c, d", "a, b, c & d"),
    ]
    all_pass = True
    for raw, expected in cases:
        result = normalize_artist(raw)
        status = '✓' if result == expected else '✗'
        if result != expected:
            all_pass = False
        print(f"  {status} '{raw}'\n      → '{result}' {'(expected: ' + expected + ')' if result != expected else ''}")
    print(f"\n{'all tests passed' if all_pass else 'some tests failed'}")
