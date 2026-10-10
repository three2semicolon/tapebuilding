"""lib.catalog.matcher - match a spotify track row against the crate catalog.
- row_access.py: Field access helpers
- normalization.py: General normalization and helper functions
- soundcloud_helpers.py: SoundCloud-specific helper functions
- match_index.py: MatchIndex class for efficient matching
"""

from .row_access import (
    _row_get, _row_title, _row_artist, _row_album,
    _row_duration_seconds, _row_track_number, _row_track_id
)
from .normalization import (
    _raw_key, _entry_artist_set, _entry_primary, _row_artist_set,
    _row_primary, _duration_close, _artists_contradict, _pick_best,
    FUZZY_RATIO_THRESHOLD, FUZZY_PREFIX_LEN, _TIER_NAMES, _TOLERANCE
)
from .soundcloud_helpers import _soundcloud_title_variations, _is_soundcloud_like_title
from .match_index import MatchIndex, match_rows, tier_name

__all__ = [
    '_row_get', '_row_title', '_row_artist', '_row_album',
    '_row_duration_seconds', '_row_track_number', '_row_track_id',
    '_raw_key', '_entry_artist_set', '_entry_primary', '_row_artist_set',
    '_row_primary', '_duration_close', '_artists_contradict', '_pick_best',
    'FUZZY_RATIO_THRESHOLD', 'FUZZY_PREFIX_LEN', '_TIER_NAMES', '_TOLERANCE',
    '_soundcloud_title_variations', '_is_soundcloud_like_title',
    'MatchIndex', 'match_rows', 'tier_name'
]