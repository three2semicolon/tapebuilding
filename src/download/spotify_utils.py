

import os
import re
import csv
import json
from datetime import datetime
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI', 'http://localhost:8888/callback')
SPOTIFY_USER_ID = os.getenv('SPOTIFY_USER_ID')


def authenticate_spotify():
    if not all([SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET]):
        raise ValueError("spotify credentials not found, set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env")

    scope = "playlist-read-private playlist-read-collaborative user-library-read user-follow-read"

    auth_manager = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=scope,
        cache_path="token_cache"
    )

    return spotipy.Spotify(auth_manager=auth_manager)


def get_user_playlists(sp, my_playlists_only=False):
    print("fetching user playlists...")
    playlists = []
    results = sp.current_user_playlists(limit=50)

    current_user_id = None
    if my_playlists_only:
        try:
            current_user = sp.current_user()
            current_user_id = current_user.get('id')
        except Exception as e:
            print(f"warning: could not get current user id for filtering: {e}")
            current_user_id = None

    while results:
        for playlist in results.get('items', []):
            playlist_url = ''
            if playlist.get('external_urls') and isinstance(playlist['external_urls'], dict):
                playlist_url = playlist['external_urls'].get('spotify', '')

            owner_id = playlist.get('owner', {}).get('id')
            if my_playlists_only and current_user_id and owner_id != current_user_id:
                continue

            playlists.append({
                'id': playlist.get('id', ''),
                'name': playlist.get('name', ''),
                'description': playlist.get('description', ''),
                'owner': playlist.get('owner', {}).get('display_name', ''),
                'public': playlist.get('public', False),
                'track_count': playlist.get('tracks', {}).get('total', 0),
                'playlist_url': playlist_url
            })

        if results.get('next'):
            results = sp.next(results)
        else:
            break

    return playlists


def get_playlist_tracks(sp, playlist_id, playlist_name):
    print(f"  fetching tracks from playlist: {playlist_name}")
    tracks = []
    results = sp.playlist_tracks(playlist_id, limit=100)

    while results:
        for item in results.get('items', []):
            track = item.get('track')
            if track:
                track_id = track.get('id', '')
                track_name = track.get('name', '')
                artists = track.get('artists', [])
                artist_names = ', '.join([artist.get('name', '') for artist in artists]) if artists else ''
                album = track.get('album', {})
                album_name = album.get('name', '') if album else ''
                duration_ms = track.get('duration_ms', 0)
                explicit = track.get('explicit', False)
                popularity = track.get('popularity', 0)
                added_at = item.get('added_at', '')
                added_by = item.get('added_by', {})
                added_by_id = added_by.get('id') if added_by else None

                spotify_url = ''
                external_urls = track.get('external_urls', {})
                if isinstance(external_urls, dict):
                    spotify_url = external_urls.get('spotify', '')

                track_number = track.get('track_number', 0)
                disc_number = track.get('disc_number', 0)
                is_local = track.get('is_local', False)

                tracks.append({
                    'playlist_id': playlist_id,
                    'playlist_name': playlist_name,
                    'track_id': track_id,
                    'track_name': track_name,
                    'artist_names': artist_names,
                    'album_name': album_name,
                    'duration_ms': duration_ms,
                    'explicit': explicit,
                    'popularity': popularity,
                    'added_at': added_at,
                    'added_by': added_by_id,
                    'spotify_url': spotify_url,
                    'track_number': track_number,
                    'disc_number': disc_number,
                    'is_local': is_local
                })

        if results.get('next'):
            results = sp.next(results)
        else:
            break

    return tracks


def get_liked_songs(sp):
    print("fetching liked songs...")
    tracks = []
    results = sp.current_user_saved_tracks(limit=50)

    while results:
        for item in results.get('items', []):
            track = item.get('track')
            if track:
                track_id = track.get('id', '')
                track_name = track.get('name', '')
                artists = track.get('artists', [])
                artist_names = ', '.join([artist.get('name', '') for artist in artists]) if artists else ''
                album = track.get('album', {})
                album_name = album.get('name', '') if album else ''
                duration_ms = track.get('duration_ms', 0)
                explicit = track.get('explicit', False)
                popularity = track.get('popularity', 0)
                added_at = item.get('added_at', '')
                added_by = item.get('added_by', {})
                added_by_id = added_by.get('id') if added_by else None

                spotify_url = ''
                external_urls = track.get('external_urls', {})
                if isinstance(external_urls, dict):
                    spotify_url = external_urls.get('spotify', '')

                track_number = track.get('track_number', 0)
                disc_number = track.get('disc_number', 0)
                is_local = track.get('is_local', False)

                tracks.append({
                    'playlist_id': 'liked_songs',
                    'playlist_name': 'Liked Songs',
                    'track_id': track_id,
                    'track_name': track_name,
                    'artist_names': artist_names,
                    'album_name': album_name,
                    'duration_ms': duration_ms,
                    'explicit': explicit,
                    'popularity': popularity,
                    'added_at': added_at,
                    'added_by': added_by_id,
                    'spotify_url': spotify_url,
                    'track_number': track_number,
                    'disc_number': disc_number,
                    'is_local': is_local
                })

        if results.get('next'):
            results = sp.next(results)
        else:
            break

    return tracks


def _normalize_title(s):
    s = s.lower()
    s = re.sub(r'\s*(feat\.?|ft\.?|featuring)\s+.*', '', s)
    s = re.sub(r'\s*\(.*?\)', '', s)
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _fuzzy_key(track):
    artists = track.get('artist_names', '')
    primary = artists.split(',')[0].strip() if artists else ''
    title = track.get('track_name', '')
    return f"{_normalize_title(primary)}|||{_normalize_title(title)}"


def merge_and_deduplicate(playlists_data, liked_songs_data):
    """two-pass: dedup by spotify track id, then by normalized primary-artist + title
    to collapse remasters/regional versions; on a fuzzy collision keep the more
    popular track as the canonical download url."""
    print("merging and deduplicating tracks...")

    all_tracks = playlists_data + liked_songs_data

    track_dict = {}

    for track in all_tracks:
        track_id = track.get('track_id', '')
        if not track_id:
            continue

        if track_id not in track_dict:
            track_dict[track_id] = {
                **track,
                'playlist_names': [track.get('playlist_name', '')],
                'playlist_ids': [track.get('playlist_id', '')]
            }
        else:
            playlist_name = track.get('playlist_name', '')
            playlist_id_val = track.get('playlist_id', '')
            if playlist_name and playlist_name not in track_dict[track_id]['playlist_names']:
                track_dict[track_id]['playlist_names'].append(playlist_name)
                if playlist_id_val:
                    track_dict[track_id]['playlist_ids'].append(playlist_id_val)

    id_deduped = []
    for track_id, track_data in track_dict.items():
        id_deduped.append({
            'track_id': track_data.get('track_id', ''),
            'track_name': track_data.get('track_name', ''),
            'artist_names': track_data.get('artist_names', ''),
            'album_name': track_data.get('album_name', ''),
            'duration_ms': track_data.get('duration_ms', 0),
            'explicit': track_data.get('explicit', False),
            'popularity': track_data.get('popularity', 0),
            'playlist_names': '; '.join([name for name in track_data.get('playlist_names', []) if name]),
            'playlist_ids': '; '.join([pid for pid in track_data.get('playlist_ids', []) if pid]),
            'playlist_count': len([name for name in track_data.get('playlist_names', []) if name]),
            'spotify_url': track_data.get('spotify_url', '')
        })

    # second pass: fuzzy dedup by primary-artist + title; on collision, merge the
    # dropped track's playlist memberships into the keeper
    fuzzy_dict = {}
    for track in id_deduped:
        key = _fuzzy_key(track)
        if key not in fuzzy_dict:
            fuzzy_dict[key] = track
        else:
            existing = fuzzy_dict[key]
            if track.get('popularity', 0) > existing.get('popularity', 0):
                existing_playlists = set(existing.get('playlist_names', '').split('; '))
                new_playlists = set(track.get('playlist_names', '').split('; '))
                merged = sorted([p for p in existing_playlists | new_playlists if p])
                track['playlist_names'] = '; '.join(merged)
                track['playlist_count'] = len(merged)
                fuzzy_dict[key] = track
            else:
                existing_playlists = set(existing.get('playlist_names', '').split('; '))
                new_playlists = set(track.get('playlist_names', '').split('; '))
                merged = sorted([p for p in existing_playlists | new_playlists if p])
                existing['playlist_names'] = '; '.join(merged)
                existing['playlist_count'] = len(merged)

    deduped_tracks = list(fuzzy_dict.values())
    fuzzy_removed = len(id_deduped) - len(deduped_tracks)
    if fuzzy_removed:
        print(f"fuzzy dedup removed {fuzzy_removed} additional duplicate(s) (remasters/regional versions)")

    deduped_tracks.sort(key=lambda x: x.get('track_name', '').lower())
    return deduped_tracks


def export_to_csv(data, filename, export_dir):
    if not data:
        print(f"no data to export for {filename}")
        return

    filepath = os.path.join(export_dir, filename)
    fieldnames = data[0].keys()
    with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

    print(f"exported {len(data)} rows to {filepath}")


def export_manifest_as_txt(tracks, export_dir):
    txt_filepath = os.path.join(export_dir, 'spotify_manifest_urls.txt')

    with open(txt_filepath, 'w', encoding='utf-8') as f:
        for track in tracks:
            spotify_url = track.get('spotify_url', '')
            if spotify_url:
                f.write(spotify_url + '\n')

    url_count = len([t for t in tracks if t.get('spotify_url', '')])
    print(f"exported {url_count} spotify urls to {txt_filepath}")


def get_export_dir(base_dir=None):
    if base_dir is None:
        base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'export')

    os.makedirs(base_dir, exist_ok=True)
    return base_dir