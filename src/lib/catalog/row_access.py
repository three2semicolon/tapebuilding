"""lib.catalog.row_access - helper functions for accessing fields from spotify rows and catalog entries.

Extracted from matcher.py to reduce file size and improve organization.
"""

def _row_get(row, *names, default=None):
    for name in names:
        if isinstance(row, dict):
            if name in row and row[name] not in (None, ''):
                return row[name]
        else:
            value = getattr(row, name, None)
            if value not in (None, ''):
                return value
    return default


def _row_title(row):
    # 'track_name' is the actual spotify_export.py / spotify_manifest.csv
    # column; 'title'/'name' kept as fallbacks for non-CSV-derived rows.
    return _row_get(row, 'track_name', 'title', 'name', default='') or ''


def _row_artist(row):
    # 'artist_names' is the actual CSV column - a "A, B & C" credit string,
    # same shape split_artists()/primary_artist() already expect.
    return _row_get(row, 'artist_names', 'artist', 'artists', default='') or ''


def _row_album(row):
    return _row_get(row, 'album_name', 'album', default='') or ''


def _row_duration_seconds(row):
    # CSV rows carry duration_ms (spotify's native unit); 'length'/'duration'
    # kept as fallbacks for already-seconds sources (e.g. a catalog-shaped row).
    ms = _row_get(row, 'duration_ms')
    if ms is not None:
        try:
            return float(ms) / 1000.0
        except (TypeError, ValueError):
            pass
    seconds = _row_get(row, 'length', 'duration', 'duration_s', 'duration_sec')
    if seconds is not None:
        try:
            return float(seconds)
        except (TypeError, ValueError):
            pass
    return None


def _row_track_number(row):
    n = _row_get(row, 'track_number', 'track')
    try:
        return int(str(n).split('/')[0])
    except (TypeError, ValueError):
        return None


def _row_track_id(row):
    return _row_get(row, 'track_id', 'id', 'spotify_id')