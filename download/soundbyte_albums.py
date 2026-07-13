#!/usr/bin/env python3
"""
download/soundbyte_albums.py

pulls top N albums from soundbyte firestore, searches for each on spotify,
and outputs:
  soundbyte_albums.csv        rank, title, artist, year, album_id, spotify_url
  soundbyte_album_urls.txt    spotify album urls for spotdl (one per line)

with --expand-albums, also expands each spotify album into its individual
tracks and outputs a track-level manifest:
  soundbyte_tracks.csv        track_id,track_name,artist_names,album_name,
                              duration_ms,explicit,popularity,
                              playlist_names,playlist_ids,playlist_count,
                              spotify_url   (same columns as spotify_manifest.csv)
  soundbyte_track_urls.txt    spotify track urls (one per line)

spotdl accepts album urls directly, so for a plain download you can skip
expansion and feed soundbyte_album_urls.txt straight to `spotify`. the only
reason to expand first is to run `spotify --pre-skip-existing` against your
library - that flag predicts `artist - title.mp3` filenames from the csv's
track metadata, and the album-url text file has no track metadata, so its
existence check skips nothing. the expanded track csv has that metadata.

requirements:
  firebase-admin (a dependency in pyproject.toml)
  FIREBASE_PROJECT_ID and FIREBASE_CREDENTIALS_PATH in .env

usage:
  uv run python -m download.soundbyte_albums
  uv run python -m download.soundbyte_albums --limit 200 --output export/
  uv run python -m download.soundbyte_albums --limit 200 --skip-spotify
  uv run python -m download.soundbyte_albums --limit 200 --expand-albums
"""

import argparse
import csv
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_LIMIT = 200

# columns of spotify_manifest.csv - the track-level csv we expand into must
# match this exactly so download_spotify's --pre-skip-existing can read
# track_name/artist_names and predict `artist - title.mp3` filenames.
MANIFEST_FIELDS = [
    'track_id', 'track_name', 'artist_names', 'album_name',
    'duration_ms', 'explicit', 'popularity',
    'playlist_names', 'playlist_ids', 'playlist_count',
    'spotify_url',
]


def fetch_from_firestore(limit=DEFAULT_LIMIT):
    """pull top `limit` albums from soundbyte firestore ordered by ranking."""
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError:
        print("error: firebase-admin not installed. run: uv add firebase-admin")
        sys.exit(1)

    creds_path = os.getenv('FIREBASE_CREDENTIALS_PATH')
    project_id = os.getenv('FIREBASE_PROJECT_ID')

    if not creds_path or not os.path.exists(creds_path):
        print("error: FIREBASE_CREDENTIALS_PATH not set or file not found.")
        print("  1. firebase console → project settings → service accounts")
        print("  2. generate new private key, save the json")
        print("  3. set FIREBASE_CREDENTIALS_PATH=/path/to/key.json in .env")
        sys.exit(1)

    print(f"connecting to firestore (project: {project_id or 'from credentials'})...")

    # initialize only once
    if not firebase_admin._apps:
        cred = credentials.Certificate(creds_path)
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    print(f"fetching top {limit} albums...")

    docs = (
        db.collection('albums')
        .order_by('ranking')
        .limit(limit)
        .stream()
    )

    albums = []
    for doc in docs:
        data = doc.to_dict()
        albums.append({
            'rank':       data.get('ranking', 0),
            'title':      data.get('album', ''),
            'artist':     data.get('artist', ''),
            'year':       data.get('year', ''),
            'album_id':   data.get('albumID', doc.id),
            'spotify_url': '',
        })

    print(f"found {len(albums)} albums in firestore")
    return albums


def _get_spotify_token():
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    if not client_id or not client_secret:
        raise ValueError("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in .env")
    resp = requests.post(
        'https://accounts.spotify.com/api/token',
        data={'grant_type': 'client_credentials'},
        auth=(client_id, client_secret),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()['access_token']


def search_spotify_album(token, title, artist):
    """search spotify for an album, return its url or '' if not found.
    tries progressively looser queries until something matches."""
    queries = [
        f'album:"{title}" artist:"{artist}"',   # exact
        f'album:"{title}" {artist}',             # loose artist
        f'{title} {artist}',                     # freeform
    ]
    headers = {'Authorization': f'Bearer {token}'}

    for query in queries:
        try:
            resp = requests.get(
                'https://api.spotify.com/v1/search',
                headers=headers,
                params={'q': query, 'type': 'album', 'limit': 5},
                timeout=10,
            )
            resp.raise_for_status()
            items = resp.json().get('albums', {}).get('items', [])
            if not items:
                continue
            # prefer exact title match
            for item in items:
                if item['name'].lower() == title.lower():
                    return item['external_urls']['spotify']
            # fall back to first result
            return items[0]['external_urls']['spotify']
        except Exception as e:
            print(f"  warning: spotify search error for '{title}': {e}")
            time.sleep(1)

    return ''


def enrich_with_spotify(albums, delay=0.3):
    """add spotify_url to each album dict in place."""
    print(f"\nsearching spotify for {len(albums)} albums...")
    try:
        token = _get_spotify_token()
    except Exception as e:
        print(f"error getting spotify token: {e}")
        return

    for i, album in enumerate(albums, 1):
        url = search_spotify_album(token, album['title'], album['artist'])
        album['spotify_url'] = url
        status = '✓' if url else '✗'
        print(f"  [{i}/{len(albums)}] {status}  {album['artist']} - {album['title']}")
        time.sleep(delay)


def export_albums(albums, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    csv_path = os.path.join(output_dir, 'soundbyte_albums.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f, fieldnames=['rank', 'title', 'artist', 'year', 'album_id', 'spotify_url']
        )
        writer.writeheader()
        writer.writerows(albums)
    print(f"\nexported {len(albums)} albums → {csv_path}")

    found = [a for a in albums if a['spotify_url']]
    urls_path = os.path.join(output_dir, 'soundbyte_album_urls.txt')
    with open(urls_path, 'w', encoding='utf-8') as f:
        for album in found:
            f.write(album['spotify_url'] + '\n')
    print(f"exported {len(found)} spotify urls → {urls_path}")

    missing = [a for a in albums if not a['spotify_url']]
    if missing:
        print(f"\n{len(missing)} album(s) not found on spotify:")
        for a in missing:
            print(f"  #{a['rank']:>3}  {a['artist']} - {a['title']} ({a['year']})")

    return csv_path, urls_path


def _extract_album_id(spotify_url):
    """extract the spotify album id from an album url."""
    m = re.search(r'(?:/album/|spotify:album:)([A-Za-z0-9]+)', spotify_url)
    return m.group(1) if m else ''


def fetch_album_tracks(token, album_id, delay=0.3):
    """fetch an album's tracks from spotify /v1/albums/{id} (paginated).
    returns (album_name, [simplified track items]). simplified items lack
    popularity, so popularity defaults to 0 in the row builder below."""
    headers = {'Authorization': f'Bearer {token}'}
    url = f'https://api.spotify.com/v1/albums/{album_id}'
    album_name = ''
    items = []
    first = True
    try:
        while url:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if first:
                album_name = data.get('name', '')
                paging = data.get('tracks', {})
                items.extend(paging.get('items', []))
                url = paging.get('next')
                first = False
            else:
                items.extend(data.get('items', []))
                url = data.get('next')
            time.sleep(delay)
    except Exception as e:
        print(f"  warning: failed to fetch tracks for album {album_id}: {e}")
    return album_name, items


def _track_row(simplified_track, album_name):
    """build a track dict matching MANIFEST_FIELDS (same columns as spotify_manifest.csv)."""
    artists = simplified_track.get('artists', [])
    artist_names = ', '.join(a.get('name', '') for a in artists) if artists else ''
    external_urls = simplified_track.get('external_urls', {})
    spotify_url = external_urls.get('spotify', '') if isinstance(external_urls, dict) else ''
    return {
        'track_id': simplified_track.get('id', ''),
        'track_name': simplified_track.get('name', ''),
        'artist_names': artist_names,
        'album_name': album_name,
        'duration_ms': simplified_track.get('duration_ms', 0),
        'explicit': simplified_track.get('explicit', False),
        'popularity': simplified_track.get('popularity', 0),
        'playlist_names': '',
        'playlist_ids': '',
        'playlist_count': 0,
        'spotify_url': spotify_url,
    }


def expand_albums_to_tracks(albums, delay=0.3):
    """expand each spotify album url into its tracks. returns a list of track
    dicts (MANIFEST_FIELDS shape) in album-rank order, deduped by spotify_url
    (a track on both a top album and a compilation only needs one file)."""
    try:
        token = _get_spotify_token()
    except Exception as e:
        print(f"error getting spotify token: {e}")
        return []

    found = [a for a in albums if a.get('spotify_url')]
    print(f"\nexpanding {len(found)} album(s) into tracks...")

    track_rows = []
    seen_urls = set()
    for i, album in enumerate(found, 1):
        album_id = _extract_album_id(album['spotify_url'])
        if not album_id:
            print(f"  [{i}/{len(found)}] ✗  {album['artist']} - {album['title']}: bad url")
            continue

        album_name, items = fetch_album_tracks(token, album_id, delay)
        added = 0
        for item in items:
            row = _track_row(item, album_name)
            url = row['spotify_url']
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            track_rows.append(row)
            added += 1
        print(f"  [{i}/{len(found)}] + {added:>3}  {album['artist']} - {album['title']}")

    print(f"expanded {len(found)} album(s) → {len(track_rows)} unique tracks")
    return track_rows


def export_tracks(track_rows, output_dir):
    """write the track-level manifest (spotify_manifest.csv columns) + a txt of
    track urls. feed the csv - not the txt - to `spotify --pre-skip-existing`;
    the txt has no track metadata, so its existence check would skip nothing."""
    os.makedirs(output_dir, exist_ok=True)

    csv_path = os.path.join(output_dir, 'soundbyte_tracks.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(track_rows)
    print(f"\nexported {len(track_rows)} tracks → {csv_path}")

    urls_path = os.path.join(output_dir, 'soundbyte_track_urls.txt')
    with open(urls_path, 'w', encoding='utf-8') as f:
        for row in track_rows:
            if row.get('spotify_url'):
                f.write(row['spotify_url'] + '\n')
    print(f"exported {len(track_rows)} track urls → {urls_path}")

    return csv_path, urls_path


def main():
    parser = argparse.ArgumentParser(
        description='export top soundbyte albums from firestore and find them on spotify'
    )
    parser.add_argument('--limit', '-n', type=int, default=DEFAULT_LIMIT,
                        help=f'number of top albums to fetch (default: {DEFAULT_LIMIT})')
    parser.add_argument('--output', '-o', type=str, default='export',
                        help='output directory (default: export/)')
    parser.add_argument('--skip-spotify', action='store_true',
                        help='fetch from firestore only, skip spotify search')
    parser.add_argument('--delay', type=float, default=0.3,
                        help='seconds between spotify api calls (default: 0.3)')
    parser.add_argument('--expand-albums', action='store_true',
                        help='also expand each spotify album into its tracks and write '
                             'soundbyte_tracks.csv (spotify_manifest.csv format) for use '
                             'with spotify --pre-skip-existing')
    args = parser.parse_args()

    try:
        albums = fetch_from_firestore(limit=args.limit)
        if not args.skip_spotify:
            enrich_with_spotify(albums, delay=args.delay)
        export_albums(albums, args.output)

        if args.expand_albums:
            if args.skip_spotify:
                print("note: --expand-albums needs spotify urls - skipping (drop --skip-spotify).")
            else:
                tracks = expand_albums_to_tracks(albums, delay=args.delay)
                if tracks:
                    export_tracks(tracks, args.output)
                else:
                    print("no tracks to export.")
    except Exception as e:
        print(f"error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
