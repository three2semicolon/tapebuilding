"""download.soundcloud_export - export soundcloud sets + liked songs to csv,
and build a deduplicated manifest of track urls for `download soundcloud`.

"""

import os
import re

import yt_dlp

from lib.text import normalize_key


def _extract_artist_title_from_url(url):
    """Extract artist and title from a SoundCloud URL as fallback.

    Expected format: https://soundcloud.com/ARTIST/TITLE
    Returns tuple (artist, title) or (None, None) if pattern doesn't match.
    """
    match = re.match(r'https?://soundcloud\.com/([^/]+)/([^/?#]+)', url)
    if match:
        artist = match.group(1)
        title = match.group(2)
        # Clean up common URL encoding issues
        artist = artist.replace('-', ' ').replace('_', ' ')
        title = title.replace('-', ' ').replace('_', ' ')
        return artist, title
    return None, None


def _extract_info(url, cookies_from_browser=None):
    """Extract info from url using yt-dlp with extract_flat=True."""
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'skip_download': True,
    }
    if cookies_from_browser:
        ydl_opts['cookiesfrombrowser'] = (cookies_from_browser,)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def list_user_sets(profile_url_or_username, cookies_from_browser=None):
    """Return list of dicts for each set: {'name', 'url', 'track_count'}."""
    # Normalize to URL
    if not profile_url_or_username.startswith('http'):
        profile_url_or_username = f'https://soundcloud.com/{profile_url_or_username}/sets'
    info = _extract_info(profile_url_or_username, cookies_from_browser)
    if not info or 'entries' not in info:
        return []
    sets = []
    for entry in info.get('entries', []):
        sets.append({
            'name': entry.get('title', ''),
            'url': entry.get('url', ''),
            'track_count': entry.get('track_count', 0) or entry.get('playlist_count', 0),
        })
    return sets


def list_user_likes(profile_url_or_username, cookies_from_browser=None):
    """Return list of dicts for each liked track: analogous to a set of one track."""
    if not profile_url_or_username.startswith('http'):
        profile_url_or_username = f'https://soundcloud.com/{profile_url_or_username}/likes'
    info = _extract_info(profile_url_or_username, cookies_from_browser)
    if not info or 'entries' not in info:
        return []
    likes = []
    for entry in info.get('entries', []):
        name = entry.get('title', '')
        uploader = entry.get('uploader', '')
        url = entry.get('url', '')

        # Fallback: extract artist and title from URL if not provided by yt-dlp
        if url:
            fallback_artist, fallback_title = _extract_artist_title_from_url(url)
            if not name and fallback_title:
                name = fallback_title
            if not uploader and fallback_artist:
                uploader = fallback_artist

        likes.append({
            'name': name,
            'uploader': uploader,
            'url': url,
            'track_count': 1,  # each like is a single track
        })
    return likes


def export_set(set_url, cookies_from_browser=None):
    """Export one set to track rows: each dict with 'title', 'uploader', 'track_url', 'position'."""
    info = _extract_info(set_url, cookies_from_browser)
    if not info or 'entries' not in info:
        return []
    tracks = []
    for i, entry in enumerate(info.get('entries', []), start=1):
        title = entry.get('title', '')
        uploader = entry.get('uploader', '')
        track_url = entry.get('url', '')

        # Fallback: extract artist and title from URL if not provided by yt-dlp
        if track_url:
            fallback_artist, fallback_title = _extract_artist_title_from_url(track_url)
            if not title and fallback_title:
                title = fallback_title
            if not uploader and fallback_artist:
                uploader = fallback_artist

        tracks.append({
            'title': title,
            'uploader': uploader,
            'track_url': track_url,
            'position': i,
        })
    return tracks


def _soundcloud_track_key(track):
    """Return a deduplication key for a SoundCloud track.
    Primary: track URL. Secondary: normalized title + normalized uploader.
    """
    track_url = track.get('track_url', '')
    if track_url:
        return ('url', track_url)
    # Fallback to normalized title + uploader
    title = normalize_key(track.get('title', ''))
    uploader = normalize_key(track.get('uploader', ''))
    return ('fallback', f'{title}|{uploader}')


def merge_and_deduplicate(track_lists):
    """Merge multiple lists of track dicts, deduplicating by _soundcloud_track_key.
    Returns list of unique tracks, preserving order of first appearance.
    """
    seen = set()
    unique_tracks = []
    for track_list in track_lists:
        for track in track_list:
            key = _soundcloud_track_key(track)
            if key not in seen:
                seen.add(key)
                unique_tracks.append(track)
    return unique_tracks


def export_specific_set(sp, set_identifier, export_dir, cookies_from_browser=None):
    """Export a specific set (url or identifier) to per-set csv/txt.
    Similar to export_specific_playlist in spotify_export.
    """
    print(f"exporting set: {set_identifier}")
    # For SoundCloud, we don't have an API client `sp`; we'll ignore it.
    # We'll treat set_identifier as a URL or a username/set name?
    # For simplicity, we assume set_identifier is a URL.
    set_url = set_identifier
    if not set_url.startswith('http'):
        # Assume it's a set name under the user? We'll need a username.
        # Since we don't have a username, we'll treat it as a URL directly.
        # This is a limitation; we'll need to improve later.
        set_url = f'https://soundcloud.com/{set_identifier}'
    info = _extract_info(set_url, cookies_from_browser)
    if not info:
        print(f"error: could not fetch set info for {set_identifier}")
        return []
    set_name = info.get('title', 'Unknown Set')
    print(f"found set: {set_name}")
    tracks = export_set(set_url, cookies_from_browser)
    print(f"found {len(tracks)} tracks")
    # Create safe filename
    safe_name = "".join(c for c in set_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    safe_name = safe_name.replace(' ', '_')
    filename = f"set_{safe_name}.csv"
    # We'll need to write CSV with columns: title, uploader, track_url, position
    _write_csv(tracks, filename, export_dir, fields=('title', 'uploader', 'track_url', 'position'))
    txt_filename = f"set_{safe_name}_urls.txt"
    txt_filepath = os.path.join(export_dir, txt_filename)
    with open(txt_filepath, 'w', encoding='utf-8') as f:
        for track in tracks:
            f.write(track.get('track_url', '') + '\n')
    print(f"exported {len(tracks)} track urls to {txt_filepath}")
    return tracks


def export_sets(sp, set_identifiers, export_dir, cookies_from_browser=None, include_likes=False):
    """Export a list of specific sets (urls or identifiers) -
    each to its own per-set csv/txt, then merge all their tracks into one deduped
    'soundcloud_manifest.csv' + urls txt.
    Also creates playlist-format files for use with playlists command."""
    seen = set()
    deduped = []
    for identifier in set_identifiers:
        if identifier not in seen:
            seen.add(identifier)
            deduped.append(identifier)

    print(f"exporting {len(deduped)} set(s)...")
    all_tracks = []
    # Data for playlist-format files: map set_id to list of tracks
    tracks_by_set = {}

    for identifier in deduped:
        tracks = export_specific_set(sp, identifier, export_dir, cookies_from_browser)
        all_tracks.extend(tracks)
        tracks_by_set[identifier] = tracks

    # Deduplicate across sets
    manifest_tracks = merge_and_deduplicate([all_tracks])
    print(f"created soundcloud manifest with {len(manifest_tracks)} unique tracks")

    _write_csv(manifest_tracks, 'soundcloud_manifest.csv', export_dir,
               fields=('title', 'uploader', 'track_url', 'position'))
    _write_manifest_as_txt(manifest_tracks, export_dir, filename='soundcloud_manifest_urls.txt')

    # Create playlist-format files for playlists command
    create_playlist_format_files(tracks_by_set, export_dir)

    return manifest_tracks


def export_all_data(sp, export_dir, cookies_from_browser=None, include_likes=False, my_sets_only=True):
    """Export all sets (and optionally likes) for a user.
    Similar to export_all_data in spotify_export.
    """
    # For SoundCloud, we need a username to fetch sets/likes.
    # We'll assume the username is derived from SPOTIFY_USER_ID? Not correct.
    # We'll need to add a SOUNDCLOUD_USERNAME env var or similar.
    # For now, we'll stub and print a warning.
    print("warning: SoundCloud export_all_data not fully implemented; need username.")
    return []


def _write_csv(rows, filename, export_dir, fields):
    """Write rows to CSV file in export_dir."""
    if not rows:
        # Still write header?
        pass
    os.makedirs(export_dir, exist_ok=True)
    path = os.path.join(export_dir, filename)
    # atomic write via temp
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8-sig', newline='') as f:
            import csv
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, path)
    except Exception as e:
        print(f"warning: could not write {path}: {e}")


def _write_manifest_as_txt(rows, export_dir, filename):
    """Write track URLs to a text file."""
    os.makedirs(export_dir, exist_ok=True)
    path = os.path.join(export_dir, filename)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            for row in rows:
                f.write(row.get('track_url', '') + '\n')
        os.replace(tmp, path)
    except Exception as e:
        print(f"warning: could not write {path}: {e}")


def _convert_to_playlist_track(track, playlist_id, playlist_name, track_number=None):
    """Convert a SoundCloud track dict to the format expected by playlists.build.

    Args:
        track: dict with 'title', 'uploader', 'track_url' keys
        playlist_id: identifier for the playlist/set
        playlist_name: human-readable name of the playlist/set
        track_number: position in playlist (optional, defaults to None)

    Returns:
        dict with keys matching PLAYLIST_TRACKS_FIELDS
    """
    if track_number is None:
        track_number = 0

    return {
        'playlist_id': playlist_id,
        'playlist_name': playlist_name,
        'track_id': str(hash(track.get('track_url', '')))[:16],  # Simple hash-based ID
        'track_name': track.get('title', ''),
        'artist_names': track.get('uploader', ''),
        'album_name': '',  # Not typically available for SoundCloud
        'duration_ms': 0,  # Unknown
        'explicit': False,
        'popularity': 0,  # Unknown
        'added_at': '',  # Unknown
        'added_by': '',  # Unknown
        'spotify_url': track.get('track_url', ''),  # Using SoundCloud URL as placeholder
        'track_number': track_number,
        'disc_number': 0,
        'is_local': False,
    }


def _convert_to_playlist_meta(playlist_id, playlist_name, description='',
                             owner='', owner_id='', public=True,
                             track_count=0, playlist_url=''):
    """Convert SoundCloud set data to the format expected by playlists.build for playlists.csv.

    Returns:
        dict with keys matching PLAYLIST_META_FIELDS
    }
    """
    return {
        'id': playlist_id,
        'name': playlist_name,
        'description': description,
        'owner': owner,
        'owner_id': owner_id,
        'public': public,
        'track_count': track_count,
        'playlist_url': playlist_url,
    }


def create_playlist_format_files(tracks_by_set, export_dir):
    """Create playlist-format files (playlists.csv and playlist_tracks.csv) for use with playlists command.

    Args:
        tracks_by_set: dict mapping set_id to list of tracks in that set
        export_dir: base export directory where soundcloud/ subdirectory will be created
    """
    # Data for playlist-format files
    playlist_meta_rows = []  # For playlists.csv
    playlist_track_rows = []  # For playlist_tracks.csv

    for set_id, tracks in tracks_by_set.items():
        # Use set_id as playlist name if we don't have a better name
        playlist_name = set_id

        # Add to playlist metadata
        playlist_meta_rows.append(_convert_to_playlist_meta(
            playlist_id=set_id,
            playlist_name=playlist_name,
            track_count=len(tracks)
        ))

        # Add tracks to playlist track rows
        for i, track in enumerate(tracks):
            playlist_track_rows.append(_convert_to_playlist_track(
                track=track,
                playlist_id=set_id,
                playlist_name=playlist_name,
                track_number=i+1
            ))

    # Create playlist-format files for playlists command
    soundcloud_dir = os.path.join(export_dir, 'soundcloud')
    os.makedirs(soundcloud_dir, exist_ok=True)

    if playlist_meta_rows:
        _write_csv(playlist_meta_rows, 'playlists.csv', soundcloud_dir,
                   fields=('id', 'name', 'description', 'owner', 'owner_id', 'public', 'track_count', 'playlist_url'))

    if playlist_track_rows:
        _write_csv(playlist_track_rows, 'playlist_tracks.csv', soundcloud_dir,
                   fields=('playlist_id', 'playlist_name', 'track_id', 'track_name', 'artist_names', 'album_name',
                           'duration_ms', 'explicit', 'popularity', 'added_at', 'added_by', 'spotify_url',
                           'track_number', 'disc_number', 'is_local'))