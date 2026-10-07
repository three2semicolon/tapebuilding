"""download.soundcloud_export - export soundcloud sets + liked songs to csv,
and build a deduplicated manifest of track urls for `download soundcloud`.

"""

import os

import yt_dlp

from lib.text import normalize_key


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
        likes.append({
            'name': entry.get('title', ''),
            'url': entry.get('url', ''),
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
        tracks.append({
            'title': entry.get('title', ''),
            'uploader': entry.get('uploader', ''),
            'track_url': entry.get('url', ''),
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
    'soundcloud_manifest.csv' + urls txt."""
    seen = set()
    deduped = []
    for identifier in set_identifiers:
        if identifier not in seen:
            seen.add(identifier)
            deduped.append(identifier)

    print(f"exporting {len(deduped)} set(s)...")
    all_tracks = []
    for identifier in deduped:
        all_tracks.extend(export_specific_set(sp, identifier, export_dir, cookies_from_browser))

    # Deduplicate across sets
    manifest_tracks = merge_and_deduplicate([all_tracks])
    print(f"created soundcloud manifest with {len(manifest_tracks)} unique tracks")

    _write_csv(manifest_tracks, 'soundcloud_manifest.csv', export_dir,
               fields=('title', 'uploader', 'track_url', 'position'))
    _write_manifest_as_txt(manifest_tracks, export_dir, filename='soundcloud_manifest_urls.txt')

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