"""cli - click group + dispatch for the download package.oad package.

per REFACTOR_PLAN.md's per-package cli.py split: this file owns click
option parsing, user-facing summaries, and exit codes; the actual logic
lives in plain, import-safe functions in the sibling modules
(spotify_export.py, spotify_download.py, ytdl.py, retry.py, soundbyte.py)
that never call sys.exit() or click.echo()/print --help themselves for
control flow - they return data (or, for the older spotify_export /
spotify_download / soundbyte functions, print their own progress - see
each module's docstring) and this file decides what that means for the
process exit code.

replaces the old argparse cli.py: same five operations, now one `download`
group instead of two standalone `export_main`/`spotify_main` entry points.
loads .env once here (lib.spotify_auth deliberately doesn't call
load_dotenv() itself - see its docstring).

pyproject.toml entry point:
    download = "download.cli:download"

mount into a top-level multi-package cli (once one exists) with
`top_level_group.add_command(download, name="download")`.
"""

import sys

import click
from dotenv import load_dotenv

from lib.spotify_auth import authenticate_user
from download.spotify.spotify_api import get_export_dir
from download.spotify.spotify_export import export_all_data, export_specific_playlist, export_playlists
from download.spotify.spotify_download import download_spotify
from download.soundcloud.soundcloud_download import download_soundcloud
from download.soundcloud.soundcloud_export import (
    export_sets,
    export_specific_set,
    list_user_likes,
    list_user_sets,
    merge_and_deduplicate,
)
from download.ytdl import download_ytdl, AUDIO_FORMATS
from download.retry import (
    run_retry,
    DEFAULT_FAILED,
    DEFAULT_SOFT,
    DEFAULT_OUT,
)
from download.other.soundbyte import run_soundbyte, DEFAULT_LIMIT
from lib.paths import (
    archive_path as resolve_archive_path,
    playlists_path as resolve_playlists_path,
    exports_dir as resolve_exports_dir,
)
from lib.catalog.indexer import get_index
from lib.catalog.matcher import MatchIndex, match_rows

load_dotenv()


@click.group()
def download():
    """spotify/soundcloud export/download, generic ytdl, failure retry, and soundbyte
    album pulls for the tapebuilding project."""


# --- export -------------------------------------------------------------

@download.command('export')
@click.option('--playlist', '-p', 'playlists', multiple=True,
              help='export a specific playlist by url or id, instead of '
                   'the full library (e.g. "https://open.spotify.com/'
                   'playlist/..." or a bare playlist id). repeatable - '
                   'pass multiple times to export + merge several '
                   'playlists into one scoped manifest.')
@click.option('--playlists-file', 'playlists_file',
              type=click.Path(exists=True, dir_okay=False),
              help='newline-delimited file of playlist urls/ids (blank '
                   'lines and #-comment lines ignored). combined with any '
                   '--playlist values given.')
@click.option('--output', '-o', 'output', type=click.Path(file_okay=False),
              help='output directory for csv files (defaults to '
                   'PLAYLISTS_PATH/exports).')
@click.option('--mine', is_flag=True,
              help='export only your own playlists (not followed/shared). '
                   'ignored with --playlist/--playlists-file.')
@click.option('--service', type=click.Choice(['spotify', 'soundcloud']), default='spotify', show_default=True,
              help='service to export from (spotify or soundcloud)')
@click.option('--type', 'export_type', type=click.Choice(['likes', 'sets', 'all-sets']), default='likes', show_default=True,
              help='type of data to export (likes, sets, or all-sets for soundcloud)')
@click.option('--set-ids', multiple=True,
              help='specific set ids to export (for soundcloud --type sets), repeatable')
@click.option('--user', help='soundcloud username or url (defaults to current user)')
@click.option('--archive-path', 'archive_path_opt', help='ARCHIVE_PATH (crate root) override for soundcloud crate checking')
@click.option('--check-crate/--no-check-crate', 'check_crate', default=False, show_default=True, help='check soundcloud exports against local crate to avoid re-downloading existing tracks')
def export_cmd(playlists, playlists_file, output, mine, service, export_type, set_ids, user, archive_path_opt, check_crate):
    """export spotify playlists + liked songs to csv, or soundcloud likes/sets to csv.

    SPOTIFY (default):
    with no --playlist/--playlists-file, exports the full library (all
    playlists + liked songs). with one or more, exports + merges just
    those playlists into a scoped 'playlists_manifest.csv' - useful for
    keeping a subset of playlists in sync without re-pulling everything.

    SOUNDCLOUD:
    --type likes: exports liked tracks
    --type sets: exports specific sets (--set-ids required) or all sets
    --type all-sets: exports all sets for a user
    """
    try:
        if service == 'spotify':
            identifiers = list(playlists)
            if playlists_file:
                with open(playlists_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            identifiers.append(line)

            sp = authenticate_user()
            export_dir = get_export_dir(base_dir=output)

            if len(identifiers) == 1:
                export_specific_playlist(sp, identifiers[0], export_dir)
            elif identifiers:
                export_playlists(sp, identifiers, export_dir)
            else:
                export_all_data(sp, export_dir, my_playlists_only=mine)

        elif service == 'soundcloud':
            # SoundCloud export
            export_dir = get_export_dir(base_dir=output)

            # Determine username/user to use
            soundcloud_user = user if user else 'me'  # default to current user

            if export_type == 'likes':
                click.echo(f"exporting soundcloud likes for user: {soundcloud_user}")
                likes = list_user_likes(soundcloud_user)
                # Write likes to CSV
                import csv
                likes_file = f"{export_dir}/soundcloud_likes.csv"
                with open(likes_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=['title', 'uploader', 'track_url'])
                    writer.writeheader()
                    for track in likes:
                        writer.writerow({
                            'title': track.get('name', ''),
                            'uploader': track.get('uploader', ''),
                            'track_url': track.get('url', '')
                        })
                click.echo(f"exported {len(likes)} likes to {likes_file}")

                # Also create URL manifest for download
                urls_file = f"{export_dir}/soundcloud_manifest_urls.txt"
                with open(urls_file, 'w', encoding='utf-8') as f:
                    for track in likes:
                        url = track.get('url', '')
                        if url:
                            f.write(url + '\n')
                click.echo(f"created url manifest: {urls_file}")

                # If crate checking is enabled, match against local archive
                if check_crate and archive_path_opt:
                    click.echo(f"checking soundcloud likes against crate at {archive_path_opt}")
                    _process_soundcloud_crate_check(
                        likes,
                        export_dir,
                        archive_path_opt,
                        prefix="soundcloud_likes"
                    )
                elif check_crate:
                    click.echo("error: --check-crate requires --archive-path to be specified", err=True)
                    sys.exit(1)

            elif export_type == 'sets':
                if not set_ids:
                    click.echo("error: --set-ids required for --type sets", err=True)
                    sys.exit(1)

                click.echo(f"exporting {len(set_ids)} specific soundcloud set(s) for user: {soundcloud_user}")
                # Use export_sets to get deduplicated tracks and create playlist-format files
                unique_tracks = export_sets(None, list(set_ids), export_dir)  # sp=None for soundcloud

                click.echo(f"exported {len(unique_tracks)} unique tracks from {len(set_ids)} set(s)")

                # If crate checking is enabled, match against local archive
                if check_crate and archive_path_opt:
                    click.echo(f"checking soundcloud sets against crate at {archive_path_opt}")
                    _process_soundcloud_crate_check(
                        unique_tracks,
                        export_dir,
                        archive_path_opt,
                        prefix="soundcloud_sets"
                    )
                elif check_crate:
                    click.echo("error: --check-crate requires --archive-path to be specified", err=True)
                    sys.exit(1)

            elif export_type == 'all-sets':
                click.echo(f"exporting all soundcloud sets for user: {soundcloud_user}")
                # Get all sets first
                sets = list_user_sets(soundcloud_user)
                click.echo(f"found {len(sets)} sets")

                all_tracks = []
                for soundcloud_set in sets:
                    set_id = soundcloud_set['url']
                    tracks = export_specific_set(None, set_id, export_dir)  # sp=None for soundcloud
                    all_tracks.extend(tracks)

                # Deduplicate tracks
                unique_tracks = merge_and_deduplicate([all_tracks]) if all_tracks else []

                click.echo(f"exported {len(unique_tracks)} unique tracks from {len(sets)} set(s)")

                # Create manifest files
                if unique_tracks:
                    # CSV manifest
                    manifest_csv = f"{export_dir}/soundcloud_manifest.csv"
                    with open(manifest_csv, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=['title', 'uploader', 'track_url', 'position'])
                        writer.writeheader()
                        for i, track in enumerate(unique_tracks, 1):
                            row = {
                                'title': track.get('title', ''),
                                'uploader': track.get('uploader', ''),
                                'track_url': track.get('track_url', ''),
                                'position': track.get('position', i)
                            }
                            writer.writerow(row)

                    # URL manifest
                    manifest_urls = f"{export_dir}/soundcloud_manifest_urls.txt"
                    with open(manifest_urls, 'w', encoding='utf-8') as f:
                        for track in unique_tracks:
                            url = track.get('track_url', '')
                            if url:
                                f.write(url + '\n')

                    click.echo(f"created manifest: {manifest_csv}")
                    click.echo(f"created url manifest: {manifest_urls}")

                    # If crate checking is enabled, match against local archive
                    if check_crate and archive_path_opt:
                        click.echo(f"checking soundcloud all sets against crate at {archive_path_opt}")
                        _process_soundcloud_crate_check(
                            unique_tracks,
                            export_dir,
                            archive_path_opt,
                            prefix="soundcloud_all_sets"
                        )
                    elif check_crate:
                        click.echo("error: --check-crate requires --archive-path to be specified", err=True)
                        sys.exit(1)
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


# --- spotify (spotdl download) ------------------------------------------

@download.command('spotify')
@click.option('--url-file', '-u', 'url_file', type=click.Path(),
              help='file or directory of urls/csvs to download (defaults '
                   'to <exports>/spotify_manifest_urls.txt).')
@click.option('--output', '-o', 'output', type=click.Path(file_okay=False),
              help='output directory for downloaded audio.')
@click.option('--format', '-f', 'fmt', default='mp3', show_default=True)
@click.option('--bitrate', '-b', default='320k', show_default=True)
@click.option('--overwrite-errors', is_flag=True)
@click.option('--skip-existing', is_flag=True)
@click.option('--validate-only', is_flag=True,
              help="report what would download without downloading.")
@click.option('--batch-size', type=int, default=1, show_default=True)
@click.option('--retries', type=int, default=3, show_default=True)
@click.option('--retry-delay', type=float, default=3, show_default=True,
              help='delay between retries, in seconds.')
@click.option('--pre-skip-existing', is_flag=True,
              help='check the crate for predicted filenames before '
                   'downloading and skip urls already on disk.')
@click.option('--cookies-from-browser', 'cookies_from_browser',
              help='browser name to pull cookies from (e.g. chrome, firefox).')
@click.option('--cookie-file', 'cookie_file', type=click.Path(exists=True),
              help='path to a Netscape-format cookies.txt; preferred over '
                   '--cookies-from-browser (avoids the browser file-lock issue).')
@click.option('--debug', is_flag=True,
              help='use DEBUG log level for spotdl/yt-dlp instead of INFO.')
@click.option('--spotdl-fallback/--no-spotdl-fallback', 'spotdl_fallback', default=False, show_default=True, help='prompt for YouTube URL or local file when spotdl fails to find a track.')
def spotify_cmd(url_file, output, fmt, bitrate, overwrite_errors,
                 skip_existing, validate_only, batch_size, retries,
                 retry_delay, pre_skip_existing, cookies_from_browser,
                 cookie_file, spotdl_fallback, debug):
    """download audio from spotify urls via spotdl."""
    if not url_file:
        export_dir = get_export_dir()
        url_file = f"{export_dir}/spotify_manifest_urls.txt"
        click.echo(f"using default url file: {url_file}")

    try:
        success = download_spotify(
            url_file=url_file,
            output_dir=output,
            format=fmt,
            bitrate=bitrate,
            overwrite_errors=overwrite_errors,
            skip_existing=skip_existing,
            validate_only=validate_only,
            batch_size=batch_size,
            pre_skip_existing=pre_skip_existing,
            retries=retries,
            retry_delay=retry_delay,
            cookies_from_browser=cookies_from_browser,
            cookie_file=cookie_file,
            debug=debug,
            spotdl_fallback=spotdl_fallback,
        )
        if not success:
            sys.exit(1)
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


# --- ytdl -----------------------------------------------------------------

@download.command('ytdl')
@click.argument('url')
@click.option('--output', '-o', 'output', type=click.Path(file_okay=False),
              help='output directory (defaults to ARCHIVE_PATH).')
@click.option('--format', '-f', 'audio_format', default='mp3',
              show_default=True, type=click.Choice(AUDIO_FORMATS))
@click.option('--quality', 'audio_quality', default='0', show_default=True,
              help='ffmpeg audio quality (0 = best VBR).')
@click.option('--no-thumbnail', is_flag=True,
              help="don't embed the thumbnail as cover art.")
@click.option('--overwrite', is_flag=True)
@click.option('--verbose', '-v', is_flag=True)
@click.option('--metadata-only', is_flag=True,
              help='list what would be downloaded without downloading.')
@click.option('--cookies-from-browser', 'cookies_from_browser',
              help='browser name to pull cookies from (e.g. chrome, firefox).')
@click.option('--ffmpeg', 'ffmpeg_path', type=click.Path(exists=True),
              help='ffmpeg executable path, overriding FFMPEG_PATH.')
def ytdl_cmd(url, output, audio_format, audio_quality, no_thumbnail,
             overwrite, verbose, metadata_only, cookies_from_browser,
             ffmpeg_path):
    """download a track, set/playlist, or album from any yt-dlp-supported
    source (soundcloud, youtube, ...)."""
    try:
        success = download_ytdl(
            url,
            output_dir=output,
            audio_format=audio_format,
            audio_quality=audio_quality,
            embed_thumbnail=not no_thumbnail,
            overwrite=overwrite,
            verbose=verbose,
            metadata_only=metadata_only,
            cookies_from_browser=cookies_from_browser,
            ffmpeg_path=ffmpeg_path,
        )
        if not success:
            sys.exit(1)
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)

# --- soundcloud ---------------------------------------------------------

@download.command('soundcloud')
@click.option('--url-file', '-u', 'url_file', type=click.Path(),
              help='file or directory of urls/csvs to download (defaults '
                   'to <exports>/soundcloud_manifest_urls.txt).')
@click.option('--output', '-o', 'output', type=click.Path(file_okay=False),
              help='output directory for downloaded audio.')
@click.option('--format', '-f', 'fmt', default='mp3', show_default=True)
@click.option('--bitrate', '-b', default='320k', show_default=True)
@click.option('--overwrite-errors', is_flag=True)
@click.option('--skip-existing', is_flag=True)
@click.option('--validate-only', is_flag=True,
              help="report what would download without downloading.")
@click.option('--batch-size', type=int, default=1, show_default=True)
@click.option('--retries', type=int, default=3, show_default=True)
@click.option('--retry-delay', type=float, default=3, show_default=True,
              help='delay between retries, in seconds.')
@click.option('--pre-skip-existing', is_flag=True,
              help='check the crate for predicted filenames before '
                   'downloading and skip urls already on disk.')
@click.option('--cookies-from-browser', 'cookies_from_browser',
              help='browser name to pull cookies from (e.g. chrome, firefox).')
@click.option('--cookie-file', 'cookie_file', type=click.Path(exists=True),
              help='path to a Netscape-format cookies.txt; preferred over '
                   '--cookies-from-browser (avoids the browser file-lock issue).')
@click.option('--debug', is_flag=True,
              help='use DEBUG log level for spotdl/yt-dlp instead of INFO.')
@click.option('--soundcloud-fallback/--no-soundcloud-fallback', 'soundcloud_fallback', default=False, show_default=True, help='prompt for YouTube URL or local file when soundcloud fails to find a track.')
def soundcloud_cmd(url_file, output, fmt, bitrate, overwrite_errors,
                    skip_existing, validate_only, batch_size, retries,
                    retry_delay, pre_skip_existing, cookies_from_browser,
                    cookie_file, soundcloud_fallback, debug):
    """download audio from soundcloud urls via ytdl."""
    if not url_file:
        export_dir = get_export_dir()
        url_file = f"{export_dir}/soundcloud_manifest_urls.txt"
        click.echo(f"using default url file: {url_file}")

    try:
        success = download_soundcloud(
            url_file=url_file,
            output_dir=output,
            format=fmt,
            bitrate=bitrate,
            overwrite_errors=overwrite_errors,
            skip_existing=skip_existing,
            validate_only=validate_only,
            batch_size=batch_size,
            pre_skip_existing=pre_skip_existing,
            retries=retries,
            retry_delay=retry_delay,
            cookies_from_browser=cookies_from_browser,
            cookie_file=cookie_file,
            debug=debug,
            soundcloud_fallback=soundcloud_fallback,
        )
        if not success:
            sys.exit(1)
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


# --- retry ------------------------------------------------------------

@download.command('retry')
@click.option('--failed-log', 'failed_path', type=click.Path(),
              default=DEFAULT_FAILED, show_default=True)
@click.option('--soft-log', 'soft_path', type=click.Path(),
              default=DEFAULT_SOFT, show_default=True)
@click.option('--output', '-o', 'output_path', type=click.Path(),
              default=DEFAULT_OUT, show_default=True,
              help='where to write the compiled retry list.')
@click.option('--include-unavailable', is_flag=True,
              help='include tracks spotdl marked as no longer existing '
                   '(excluded by default - retrying rarely recovers them).')
@click.option('--no-check', is_flag=True,
              help="skip the library existence re-check; just compile "
                   "and dedup the failure logs as-is.")
@click.option('--metadata-source', 'metadata_source', type=click.Path(),
              help='csv or directory of csvs for url -> artist/track/album '
                   'lookup (defaults to PLAYLISTS_PATH/exports).')
@click.option('--library-root', 'library_root', type=click.Path(),
              help='crate root to check against (defaults to ARCHIVE_PATH).')
@click.option('--report-csv', 'report_csv_path', type=click.Path(),
              help='also write a manual-hunt csv of the remaining tracks '
                   '(artist, track, album, reason, url, youtube search link).')
def retry_cmd(failed_path, soft_path, output_path, include_unavailable,
              no_check, metadata_source, library_root, report_csv_path):
    """compile failed_downloads.txt + soft_failures.txt into a retry list,
    filtered against the crate so only still-missing tracks remain."""
    try:
        result = run_retry(
            failed_path=failed_path,
            soft_path=soft_path,
            output_path=output_path,
            include_unavailable=include_unavailable,
            no_check=no_check,
            metadata_source=metadata_source,
            library_root=library_root,
            report_csv_path=report_csv_path,
        )
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)

    click.echo(f"failures seen (deduped)  : {result['total_seen']}")
    click.echo(f"excluded (unavailable)   : {len(result['hard_excluded'])}")
    if not no_check:
        click.echo(f"already on disk          : {len(result['already_on_disk'])}")
        if result['no_meta']:
            click.echo(f"no metadata (kept)       : {len(result['no_meta'])}")
    click.echo(f"retry list ({len(result['retry_urls'])})       : {result['output_path']}")
    if result['report_csv_path']:
        click.echo(f"report csv               : {result['report_csv_path']}")

    if not result['retry_urls']:
        click.echo("\nnothing left to retry.")


# --- soundbyte ----------------------------------------------------------

@download.command('soundbyte')
@click.option('--limit', type=int, default=DEFAULT_LIMIT, show_default=True,
              help='how many top-ranked albums to pull from firestore.')
@click.option('--output', '-o', 'output', type=click.Path(file_okay=False),
              help='output directory for csvs (defaults to '
                   'PLAYLISTS_PATH/exports).')
@click.option('--delay', type=float, default=0.3, show_default=True,
              help='delay between spotify api calls, in seconds.')
def soundbyte_cmd(limit, output, delay):
    """pull top-N albums from soundbyte firestore, match them on spotify,
    and export a track-level manifest for `download spotify`."""
    try:
        result = run_soundbyte(limit=limit, output_dir=output, delay=delay)
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)

    click.echo(
        f"\nmatched {result['matched_count']}/{result['total_count']} "
        f"albums on spotify -> {len(result['track_rows'])} unique tracks"
    )
    click.echo(f"album csv  : {result['album_csv_path']}")
    click.echo(f"track csv  : {result['track_csv_path']}")
    click.echo(
        f"\nfeed the track csv to `download spotify --pre-skip-existing "
        f"-u {result['track_csv_path']}` to download."
    )


def _process_soundcloud_crate_check(tracks, export_dir, archive_path, prefix):
    """Process SoundCloud tracks against local crate to avoid re-downloading existing tracks.

    Similar to the playlist unmatched logic, this:
    1. Builds an index of the local music crate/archive
    2. Matches SoundCloud track data against the crate
    3. Writes matched/unmatched CSV and TXT files for handoff to downloader
    """
    try:
        # Resolve archive path (crate root)
        library = resolve_archive_path(archive_path)
        if not os.path.isdir(library):
            click.echo(f"warning: library root not found: {library} (archive path)", err=True)
            return

        # Build index of local crate
        click.echo(f"building crate index from {library}...")
        index = get_index(library, exports_dir=export_dir, reindex=False, verbose=False)
        mindex = MatchIndex(index)

        # Prepare SoundCloud track data for matching
        # Convert to format expected by match_rows: list of dicts with track metadata
        soundcloud_rows = []
        for i, track in enumerate(tracks):
            # Extract metadata from SoundCloud track data
            # Based on what we get from list_user_likes and export_specific_set
            track_id = track.get('id', f'sc_{i}')  # Use ID if available, otherwise generate
            track_name = track.get('title', track.get('name', ''))  # title or name
            artist_names = track.get('uploader', track.get('artist', ''))  # uploader or artist
            album_name = track.get('album', '')  # album if available
            spotify_url = track.get('track_url', track.get('url', ''))  # URL

            # Create a row in the format expected by match_rows
            # Based on PLAYLIST_TRACKS_FIELDS from playlists/build.py
            row = {
                'playlist_id': prefix,  # Use prefix as playlist ID for matching
                'playlist_name': prefix.replace('_', ' ').title(),  # Human readable name
                'track_id': track_id,
                'track_name': track_name,
                'artist_names': artist_names,
                'album_name': album_name,
                'duration_ms': 0,  # Unknown for SoundCloud
                'explicit': False,
                'popularity': 0,
                'added_at': '',
                'added_by': '',
                'spotify_url': spotify_url,
                'track_number': 0,
                'disc_number': 0,
                'is_local': False,
            }
            soundcloud_rows.append(row)

        if not soundcloud_rows:
            click.echo("warning: no soundcloud tracks to check against crate")
            return

        # Perform matching against crate index
        click.echo(f"matching {len(soundcloud_rows)} soundcloud tracks against crate...")
        results = match_rows(soundcloud_rows, index=mindex, verbose=False)

        # Separate matched and unmatched tracks
        matched_entries = []
        unmatched_rows = []
        matched_count = 0
        unmatched_count = 0

        for rec in results:
            row = rec['row']
            if rec['path']:  # Matched - found in crate
                matched_count += 1
                matched_entries.append({
                    'track_id': row.get('track_id', ''),
                    'track_name': row.get('track_name', ''),
                    'artist_names': row.get('artist_names', ''),
                    'album_name': row.get('album_name', ''),
                    'spotify_url': row.get('spotify_url', ''),
                    'matched_path': rec['path'],  # Where it was found in crate
                })
            else:  # Unmatched - not in crate, needs downloading
                unmatched_count += 1
                unmatched_rows.append({
                    'track_id': row.get('track_id', ''),
                    'track_name': row.get('track_name', ''),
                    'artist_names': row.get('artist_names', ''),
                    'album_name': row.get('album_name', ''),
                    'spotify_url': row.get('spotify_url', ''),
                })

        # Write matched tracks CSV
        if matched_entries:
            matched_csv_path = f"{export_dir}/{prefix}_matched.csv"
            matched_fields = ('track_id', 'track_name', 'artist_names', 'album_name', 'spotify_url', 'matched_path')
            try:
                with open(matched_csv_path + '.tmp', 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=matched_fields)
                    writer.writeheader()
                    writer.writerows(matched_entries)
                os.replace(matched_csv_path + '.tmp', matched_csv_path)
                click.echo(f"written {len(matched_entries)} matched tracks to {matched_csv_path}")
            except OSError as e:
                click.echo(f"warning: could not write {matched_csv_path}: {e}", err=True)

        # Write unmatched tracks CSV and URL list (for downloading)
        if unmatched_rows:
            unmatched_csv_path = f"{export_dir}/{prefix}_unmatched.csv"
            unmatched_txt_path = f"{export_dir}/{prefix}_unmatched_urls.txt"
            unmatched_fields = ('track_id', 'track_name', 'artist_names', 'album_name', 'spotify_url')
            urls = []
            seen = set()
            body_lines = []
            body_lines.append(','.join(unmatched_fields))

            for r in unmatched_rows:
                body_lines.append(','.join(_csv_escape(r.get(k, '')) for k in unmatched_fields))
                u = (r.get('spotify_url') or '').strip()
                if u and u not in seen:
                    seen.add(u)
                    urls.append(u)

            try:
                # Write CSV
                with open(unmatched_csv_path + '.tmp', 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=unmatched_fields)
                    writer.writeheader()
                    writer.writerows(unmatched_rows)
                os.replace(unmatched_csv_path + '.tmp', unmatched_csv_path)

                # Write URL list
                with open(unmatched_txt_path + '.tmp', 'w', encoding='utf-8') as f:
                    f.write('\n'.join(urls) + ('\n' if urls else ''))
                os.replace(unmatched_txt_path + '.tmp', unmatched_txt_path)

                click.echo(f"written {len(unmatched_count)} unmatched tracks to {unmatched_csv_path}")
                click.echo(f"written {len(unmatched_count)} URLs to {unmatched_txt_path}")
            except OSError as e:
                click.echo(f"warning: could not write unmatched files: {e}", err=True)
        else:
            click.echo("all soundcloud tracks already exist in crate - nothing to download!")

        # Summary
        click.echo(f"\nsoundcloud crate check complete: {matched_count} matched, {unmatched_count} unmatched of {len(tracks)} total tracks")
        if unmatched_count > 0:
            click.echo(f"unmatched tracks -> {export_dir}/{prefix}_unmatched.csv")
            click.echo(f"unmatched URLs -> {export_dir}/{prefix}_unmatched_urls.txt")
            click.echo(f"to download, run: uv run download soundcloud -u {export_dir}/{prefix}_unmatched_urls.txt")

    except Exception as e:
        click.echo(f"error during soundcloud crate check: {e}", err=True)
        # Don't sys.exit(1) here - let the export succeed even if crate check fails


def _csv_escape(v):
    """Escape a value for CSV output."""
    v = str(v)
    if ',' in v or '"' in v or '\n' in v:
        v = '"' + v.replace('"', '""') + '"'
    return v


if __name__ == '__main__':
    download()
