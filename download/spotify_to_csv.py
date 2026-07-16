
"""export spotify playlists + liked songs to csv, and build a deduplicated
manifest of track urls for `spotify`."""

import argparse
import os
import sys
from .spotify_utils import (
    authenticate_spotify,
    get_user_playlists,
    get_playlist_tracks,
    get_liked_songs,
    merge_and_deduplicate,
    export_to_csv,
    export_manifest_as_txt,
    get_export_dir
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


def export_all_data(sp, export_dir, my_playlists_only=False):
    print("starting full Spotify export...")

    user = sp.current_user()
    print(f"authenticated as: {user.get('display_name', 'Unknown User')} ({user.get('id', 'Unknown ID')})")

    playlists = get_user_playlists(sp, my_playlists_only=my_playlists_only)
    if my_playlists_only:
        print(f"found {len(playlists)} of your playlists")
    else:
        print(f"found {len(playlists)} playlists")

    playlists_file = os.path.join(export_dir, 'playlists.csv')
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

def main():
    parser = argparse.ArgumentParser(description='export spotify data for the tapebuilding project')
    parser.add_argument('--playlist', '-p', type=str,
                        help='export a specific playlist by url or id (e.g. "https://open.spotify.com/playlist/..." or "37i9dQZF1DXcBWIGoYBM5M")')
    parser.add_argument('--output', '-o', type=str,
                        help='output directory for csv files (defaults to ./export/)')
    parser.add_argument('--all', '-a', action='store_true',
                        help='export all playlists and liked songs (default)')
    parser.add_argument('--mine', action='store_true',
                        help='export only your own playlists (not followed/shared)')

    args = parser.parse_args()

    try:
        sp = authenticate_spotify()

        if args.output:
            export_dir = args.output
            os.makedirs(export_dir, exist_ok=True)
        else:
            export_dir = get_export_dir()

        if args.playlist:
            export_specific_playlist(sp, args.playlist, export_dir)
        else:
            export_all_data(sp, export_dir, my_playlists_only=args.mine)

    except Exception as e:
        print(f"error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
