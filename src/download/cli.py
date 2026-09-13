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
from download.spotify_api import get_export_dir
from download.spotify_export import export_all_data, export_specific_playlist, export_playlists
from download.spotify_download import download_spotify
from download.ytdl import download_ytdl, AUDIO_FORMATS
from download.retry import (
    run_retry,
    DEFAULT_FAILED,
    DEFAULT_SOFT,
    DEFAULT_OUT,
)
from download.soundbyte import run_soundbyte, DEFAULT_LIMIT

load_dotenv()


@click.group()
def download():
    """spotify export/download, generic ytdl, failure retry, and soundbyte
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
def export_cmd(playlists, playlists_file, output, mine):
    """export spotify playlists + liked songs to csv.

    with no --playlist/--playlists-file, exports the full library (all
    playlists + liked songs). with one or more, exports + merges just
    those playlists into a scoped 'playlists_manifest.csv' - useful for
    keeping a subset of playlists in sync without re-pulling everything.
    """
    identifiers = list(playlists)
    if playlists_file:
        with open(playlists_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    identifiers.append(line)

    try:
        sp = authenticate_user()
        export_dir = get_export_dir(base_dir=output)

        if len(identifiers) == 1:
            export_specific_playlist(sp, identifiers[0], export_dir)
        elif identifiers:
            export_playlists(sp, identifiers, export_dir)
        else:
            export_all_data(sp, export_dir, my_playlists_only=mine)
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
def spotify_cmd(url_file, output, fmt, bitrate, overwrite_errors,
                 skip_existing, validate_only, batch_size, retries,
                 retry_delay, pre_skip_existing, cookies_from_browser,
                 cookie_file, debug):
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


if __name__ == '__main__':
    download()
