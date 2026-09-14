"""download.spotify_export - export spotify playlists + liked songs to csv,
and build a deduplicated manifest of track urls for `spotify_download`.

was spotify_to_csv.py. extract_playlist_id_from_url() stays in this file
(spotify-export-specific, not a generic lib/ concern) even though
playlists/build.py also imports it.

export_playlists() is new (not in the original spotify_to_csv.py): exports
a *list* of specific playlists and merges their tracks into one scoped
manifest, for keeping a subset of playlists in sync independently of the
full library export - see its own docstring.
"""

import os

from download.spotify_api import (
    get_user_playlists,
    get_playlist_tracks,
    get_liked_songs,
    merge_and_deduplicate,
    export_to_csv,
    export_manifest_as_txt,
)


def extract_playlist_id_from_url(url):
    if 'open.spotify.com/playlist/' in url:
        return url.split('open.spotify.com/playlist/')[1].split('?')[0]
    elif url.startswith('spotify:playlist:'):
        return url.split('spotify:playlist:')[1]
    else:
        return url


def export_specific_playlist(sp, playlist_identifier, export_dir):
    print(f"exporting playlist: {playlist_identifier}")

    playlist_id = extract_playlist_id_from_url(playlist_identifier)

    try:
        playlist = sp.playlist(playlist_id)
        playlist_name = playlist.get('name', 'Unknown Playlist')
        print(f"found playlist: {playlist_name}")

        tracks = get_playlist_tracks(sp, playlist_id, playlist_name)
        print(f"found {len(tracks)} tracks")

        safe_name = "".join(c for c in playlist_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_name = safe_name.replace(' ', '_')
        filename = f"playlist_{safe_name}.csv"
        export_to_csv(tracks, filename, export_dir)

        txt_filename = f"playlist_{safe_name}_urls.txt"
        txt_filepath = os.path.join(export_dir, txt_filename)
        with open(txt_filepath, 'w', encoding='utf-8') as f:
            for track in tracks:
                f.write(track.get('spotify_url', '') + '\n')
        print(f"exported {len(tracks)} spotify urls to {txt_filepath}")

        return tracks

    except Exception as e:
        print(f"error exporting playlist {playlist_identifier}: {e}")
        return []


def export_playlists(sp, playlist_identifiers, export_dir):
    """export a list of specific playlists (urls or ids, mixed is fine) -
    each to its own per-playlist csv/txt via export_specific_playlist(),
    same as always - then merge all their tracks into one deduped
    'playlists_manifest.csv' + urls txt, shaped like spotify_manifest.csv,
    so `download spotify --pre-skip-existing` can be pointed at just this
    subset instead of the full library export.

    this is the mechanism for "update only these playlists": keep a
    --playlists-file list of the ones you actually want synced, re-run
    this export against it periodically, and feed the resulting manifest
    to a --pre-skip-existing download run to fetch only what's new.

    duplicate identifiers (e.g. the same playlist passed via both
    --playlist and --playlists-file) are deduped before fetching, so a
    playlist is never re-fetched from the api twice in one run.
    """
    seen = set()
    deduped = []
    for identifier in playlist_identifiers:
        if identifier not in seen:
            seen.add(identifier)
            deduped.append(identifier)

    print(f"exporting {len(deduped)} playlist(s)...")
    all_tracks = []
    for identifier in deduped:
        all_tracks.extend(export_specific_playlist(sp, identifier, export_dir))

    # merge_and_deduplicate expects (playlist-sourced tracks, liked-songs
    # tracks) - there's no liked-songs side here, just multiple playlists,
    # so pass an empty second list. gives the same id-dedup + fuzzy
    # remaster/regional-version collapse as the full export.
    manifest_tracks = merge_and_deduplicate(all_tracks, [])
    print(f"created playlists manifest with {len(manifest_tracks)} unique tracks")

    export_to_csv(manifest_tracks, 'playlists_manifest.csv', export_dir)
    export_manifest_as_txt(manifest_tracks, export_dir, filename='playlists_manifest_urls.txt')

    return manifest_tracks


def export_all_data(sp, export_dir, my_playlists_only=False):
    print("starting full Spotify export...")

    user = sp.current_user()
    print(f"authenticated as: {user.get('display_name', 'Unknown User')} ({user.get('id', 'Unknown ID')})")

    playlists = get_user_playlists(sp, my_playlists_only=my_playlists_only)
    if my_playlists_only:
        print(f"found {len(playlists)} of your playlists")
    else:
        print(f"found {len(playlists)} playlists")

    export_to_csv(playlists, 'playlists.csv', export_dir)

    all_playlist_tracks = []
    for playlist in playlists:
        tracks = get_playlist_tracks(sp, playlist.get('id', ''), playlist.get('name', 'Unknown'))
        all_playlist_tracks.extend(tracks)
    print(f"found {len(all_playlist_tracks)} tracks in playlists")

    export_to_csv(all_playlist_tracks, 'playlist_tracks.csv', export_dir)

    liked_songs = get_liked_songs(sp)
    print(f"found {len(liked_songs)} liked songs")
    export_to_csv(liked_songs, 'liked_songs.csv', export_dir)

    manifest_tracks = merge_and_deduplicate(all_playlist_tracks, liked_songs)
    print(f"created manifest with {len(manifest_tracks)} unique tracks")

    export_to_csv(manifest_tracks, 'spotify_manifest.csv', export_dir)

    export_manifest_as_txt(manifest_tracks, export_dir)

    print("\nexport complete! files saved in:", export_dir)
    print("- playlists.csv: playlist metadata")
    print("- playlist_tracks.csv: all tracks from playlists (with duplicates)")
    print("- liked_songs.csv: all liked/saved tracks")
    print("- spotify_manifest.csv: deduplicated master manifest")
    print("- spotify_manifest_urls.txt: spotify urls for spotdl input")

    return manifest_tracks
