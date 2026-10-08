"""lib.catalog.row_access - helper functions for accessing fields from spotify rows and catalog entries.

Extracted from matcher.py to reduce file size and improve organization.
"""


def _is_soundcloud_row(row):
    """Check if a row appears to be from SoundCloud based on the spotify_url field."""
    spotify_url = _row_get(row, 'spotify_url', default='')
    return spotify_url.startswith('https://soundcloud.com/')


def _parse_soundcloud_trackname(trackname):
    """Given a trackname string that might contain both title and artist information
    separated by common delimiters, try to extract the title and artist.

    Returns a tuple (title, artist). If extraction fails, returns (trackname, '').
    """
    if not trackname:
        return ('', '')

    # List of separators to try, in order of preference
    separators = [' & ', ' and ', ',', ' ft ', ' feat ']

    # We'll try each separator and see if splitting gives us at least two parts
    for sep in separators:
        if sep in trackname:
            # Find the last occurrence of the separator to handle cases like "A & B & C"
            last_sep_pos = trackname.rfind(sep)
            if last_sep_pos != -1:
                title_candidate = trackname[:last_sep_pos].strip()
                artist_candidate = trackname[last_sep_pos + len(sep):].strip()
                if title_candidate and artist_candidate:
                    return (title_candidate, artist_candidate)

    # If no separator found or splitting didn't yield two non-empty parts, return original as title, empty artist
    return (trackname, '')


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
    title = _row_get(row, 'track_name', 'title', 'name', default='') or ''

    # If this looks like a SoundCloud row, try to parse the track_name to get a cleaner title
    if _is_soundcloud_row(row):
        track_name = _row_get(row, 'track_name', 'title', 'name', default='') or ''
        parsed_title, _ = _parse_soundcloud_trackname(track_name)
        # If we got a parsed title that is different from the original and not empty, use it
        if parsed_title and parsed_title != title:
            title = parsed_title

    return title or ''


def _row_artist(row):
    # 'artist_names' is the actual CSV column - a "A, B & C" credit string,
    # same shape split_artists()/primary_artist() already expect.
    artist = _row_get(row, 'artist_names', 'artist', 'artists', default='') or ''

    # If artist is empty and this looks like a SoundCloud row, try to extract artist from track_name
    if not artist and _is_soundcloud_row(row):
        track_name = _row_get(row, 'track_name', 'title', 'name', default='') or ''
        _, extracted_artist = _parse_soundcloud_trackname(track_name)
        if extracted_artist:
            artist = extracted_artist

    return artist


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