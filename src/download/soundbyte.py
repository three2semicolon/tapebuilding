"""download.soundbyte - pull top N albums from soundbyte firestore, search
for each on spotify, and export a manifest spotdl/spotify_download can use.

was soundbyte_albums.py. beyond the cli.py split:
- _get_spotify_token() (a second, hand-rolled client-credentials flow using
  raw `requests` calls) -> lib.spotify_auth.authenticate_client(). this is
  more than swapping the token source: authenticate_client() hands back a
  spotipy.Spotify client, not a bearer token, so search_spotify_album() and
  fetch_album_tracks() are rewritten on sp.search()/sp.album() instead of
  hand-rolled requests.get() calls against the raw web api. behavior
  (progressively loosened search queries, exact-title preference, paginated
  track fetch) is preserved - only the transport changed.
- `requests` is now only used for the firestore-unrelated... actually not at
  all - it was exclusively the old auth/search transport, so the import is
  dropped entirely.
- get_export_dir() default output dir (was a bare 'export' cwd-relative
  string) -> download.spotify_api.get_export_dir(), so soundbyte's csvs land
  in the same PLAYLISTS_PATH/exports as spotify_export.py's, unless
  --output overrides it. flagging this as a behavior change worth
  double-checking - the original always wrote to ./export regardless of
  .env.

requirements unchanged: firebase-admin, FIREBASE_PROJECT_ID +
FIREBASE_CREDENTIALS_PATH in .env.
"""

import os
import re
import sys
import time

from lib.spotify_auth import authenticate_client
from download.spotify_api import get_export_dir

DEFAULT_LIMIT = 200

# columns of spotify_manifest.csv - the track-level csv we expand into must
# match this exactly so spotify_download's --pre-skip-existing can read
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


def search_spotify_album(sp, title, artist):
    """search spotify for an album, return its url or '' if not found.
    tries progressively looser queries until something matches."""
    queries = [
        f'album:"{title}" artist:"{artist}"',   # exact
        f'album:"{title}" {artist}',             # loose artist
        f'{title} {artist}',                     # freeform
    ]

    for query in queries:
        try:
            results = sp.search(q=query, type='album', limit=5)
            items = results.get('albums', {}).get('items', [])
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


def enrich_with_spotify(sp, albums, delay=0.3):
    """add spotify_url to each album dict in place."""
    print(f"\nsearching spotify for {len(albums)} albums...")
    for i, album in enumerate(albums, 1):
        url = search_spotify_album(sp, album['title'], album['artist'])
        album['spotify_url'] = url
        status = '✓' if url else '✗'
        print(f"  [{i}/{len(albums)}] {status}  {album['artist']} - {album['title']}")
        time.sleep(delay)


def export_albums(albums, output_dir):
    import csv
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


def fetch_album_tracks(sp, album_id, delay=0.3):
    """fetch an album's tracks via spotipy's sp.album()/sp.next() paging
    (was a hand-rolled requests.get() + manual `next` url loop against
    /v1/albums/{id}). returns (album_name, [simplified track items]).
    simplified items lack popularity, so popularity defaults to 0 in the
    row builder below - same as before."""
    album_name = ''
    items = []
    try:
        album = sp.album(album_id)
        album_name = album.get('name', '')
        results = album.get('tracks', {})
        items.extend(results.get('items', []))
        while results.get('next'):
            time.sleep(delay)
            results = sp.next(results)
            items.extend(results.get('items', []))
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


def expand_albums_to_tracks(sp, albums, delay=0.3):
    """expand each spotify album url into its tracks. returns a list of track
    dicts (MANIFEST_FIELDS shape) in album-rank order, deduped by spotify_url
    (a track on both a top album and a compilation only needs one file)."""
    found = [a for a in albums if a.get('spotify_url')]
    print(f"\nexpanding {len(found)} album(s) into tracks...")

    track_rows = []
    seen_urls = set()
    for i, album in enumerate(found, 1):
        album_id = _extract_album_id(album['spotify_url'])
        if not album_id:
            print(f"  [{i}/{len(found)}] ✗  {album['artist']} - {album['title']}: bad url")
            continue

        album_name, items = fetch_album_tracks(sp, album_id, delay)
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
    import csv
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


def run_soundbyte(limit=DEFAULT_LIMIT, output_dir=None, delay=0.3):
    """full pipeline: firestore top-N albums -> spotify album search ->
    album csv/urls -> expand matched albums into a track-level manifest
    (MANIFEST_FIELDS-shaped, same columns as spotify_manifest.csv) that
    `spotify_download`/`spotify --pre-skip-existing` can consume directly.

    single entry point for cli.py, same shape as retry.run_retry(): the
    step functions above already do their own progress printing (unlike
    run_retry, which reports purely via its return dict), so this just
    sequences them and hands back the artifact paths for cli.py to
    summarize/exit-code on.
    """
    output_dir = output_dir or get_export_dir()

    albums = fetch_from_firestore(limit=limit)

    sp = authenticate_client()
    enrich_with_spotify(sp, albums, delay=delay)
    album_csv_path, album_urls_path = export_albums(albums, output_dir)

    track_rows = expand_albums_to_tracks(sp, albums, delay=delay)
    track_csv_path, track_urls_path = export_tracks(track_rows, output_dir)

    return {
        'albums': albums,
        'album_csv_path': album_csv_path,
        'album_urls_path': album_urls_path,
        'track_rows': track_rows,
        'track_csv_path': track_csv_path,
        'track_urls_path': track_urls_path,
        'matched_count': len([a for a in albums if a.get('spotify_url')]),
        'total_count': len(albums),
    }
