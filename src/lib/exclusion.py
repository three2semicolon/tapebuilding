"""lib.exclusion - shared playlist exclusion logic and playlist ID/URL parsing.

Centralises the name/ID-based playlist exclusion logic that was duplicated
between download.spotify.spotify_export.export_all_data() and
playlists.build._apply_exclude_filter(). Both build (token, as_id, is_id)
tuples from exclude names and match playlists by ID (len >= 16) or by name.
"""


def extract_playlist_id_from_url(url):
    """Extract a Spotify playlist ID from a URL, URI, or bare ID."""
    if 'open.spotify.com/playlist/' in url:
        return url.split('open.spotify.com/playlist/')[1].split('?')[0]
    elif url.startswith('spotify:playlist:'):
        return url.split('spotify:playlist:')[1]
    else:
        return url


def build_exclude_tokens(exclude_names):
    """Convert exclude tokens (names, IDs, or URLs) into
    (token, as_id, is_id) tuples for matching against playlists.

    is_id is True when the resolved ID looks like a Spotify playlist ID
    (at least 16 characters), meaning the token should be matched by ID
    rather than by name.
    """
    tokens = []
    for token in exclude_names:
        as_id = extract_playlist_id_from_url(token)
        is_id = len(as_id) >= 16
        tokens.append((token, as_id, is_id))
    return tokens


def is_playlist_excluded(playlist, exclude_tokens, match_url=False):
    """Return True if a playlist dict matches any exclude token.

    ID-mode tokens match by playlist['id']; name-mode tokens match by
    playlist['name'], and optionally by playlist['id'] or
    playlist['playlist_url'] when match_url is True.
    """
    playlist_id = playlist.get('id', '')
    playlist_name = playlist.get('name', '')
    playlist_url = playlist.get('playlist_url', '')

    for token, as_id, is_id in exclude_tokens:
        if is_id:
            if playlist_id == as_id:
                return True
        else:
            if playlist_name == token or playlist_id == token:
                return True
            if match_url and playlist_url == token:
                return True
    return False


def _matching_exclude_token(meta, exclude_tokens, match_url=False):
    """Return the exclude token that matches a playlist dict, or None.

    Mirrors is_playlist_excluded()'s matching rules so apply_exclude_filter()
    can record exactly which token matched each excluded playlist.
    """
    for token, as_id, is_id in exclude_tokens:
        if is_id:
            if meta.get("id") == as_id:
                return token
        else:
            if (meta.get("name") == token or meta.get("id") == token
                    or (match_url and meta.get("playlist_url") == token)):
                return token
    return None


def apply_exclude_filter(selected, exclude_names, match_url=False, warn_unmatched=True):
    """Filter playlist dicts, removing excluded ones.

    Args:
        selected: List of playlist dictionaries to filter.
        exclude_names: List of playlist names or IDs to exclude.
        match_url: When True, name-mode tokens also match playlist_url.
        warn_unmatched: When True, print a warning for exclude tokens that
            matched no playlist.

    Returns:
        (filtered, matched_tokens) where filtered is the list of
        non-excluded playlists and matched_tokens is the set of exclude
        tokens that matched at least one playlist.
    """
    if not exclude_names:
        return list(selected), set()

    exclude_tokens = build_exclude_tokens(exclude_names)
    matched_tokens = set()
    filtered = []

    for meta in selected:
        matched = _matching_exclude_token(meta, exclude_tokens, match_url=match_url)
        if matched is None:
            filtered.append(meta)
        else:
            matched_tokens.add(matched)

    if warn_unmatched:
        for token, _, _ in exclude_tokens:
            if token not in matched_tokens:
                print(f"warning: --exclude '{token}' did not match any playlist (skipped).")

    return filtered, matched_tokens
