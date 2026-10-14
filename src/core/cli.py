"""core.cli - click entry point + dispatch for core (renamed from pipelines).

same split as every other package's cli.py: this file owns option parsing
and exit codes; the actual logic lives in core.download_songs.run_download_songs()
and core.sync.run_sync(), neither of which call sys.exit() themselves.

replaces the old single-script `pipelines/download_songs.py` invocation with
a `core` command group so future preset workflows slot in as subcommands
the same way.

pyproject.toml entry point:
    core = "core.cli:core"
"""

import sys

import click
from dotenv import load_dotenv

from core.download_songs import run_download_songs, STEPS
from core.process_unmatched import run_process_unmatched
from core.sync import run_sync

load_dotenv()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


@click.group('core')
def core():
    """opinionated multi-step workflows stitching the domain packages together."""


@core.command('download')
@click.argument('source', required=False)
@click.option('--apply', is_flag=True, help='do it for real (default: dry run).')
@click.option('--archive-path', 'archive_path_opt', help='crate root override (default: ARCHIVE_PATH).')
@click.option('-i', '--input', 'drop_opt', help='staging drop for downloads (default: <crate>/unorganized).')
@click.option('--only', 'only_opt', multiple=True, type=click.Choice(STEPS),
              help='run only this step (repeatable); default: all three in order.')
@click.option('--format', 'format_opt', default='mp3', show_default=True,
              help='audio format for the download step.')
@click.option('--bitrate', 'bitrate_opt', default='320k', show_default=True, help='audio bitrate.')
@click.option('--verbose', is_flag=True, help='forward verbose/debug logging to each step.')
def download_cmd(source, apply, archive_path_opt, drop_opt, only_opt,
                 format_opt, bitrate_opt, verbose):
    """download -> beets-import -> playlists-refresh, in one pass."""
    result = run_download_songs(
        source=source, apply=apply, archive_path_opt=archive_path_opt,
        drop=drop_opt, only=list(only_opt) or None, format=format_opt,
        bitrate=bitrate_opt, verbose=verbose,
    )
    if not result['ok']:
        sys.exit(1)


@core.command('process-unmatched')
@click.option('--archive-path', 'archive_path_opt', help='crate root override (default: ARCHIVE_PATH).')
@click.option('--playlists-path', 'playlists_path_opt', help='PLAYLISTS_PATH override (default: PLAYLISTS_PATH/playlists).')
@click.option('--exports-dir', 'exports_dir_opt', help='exports dir override.')
@click.option('--service', type=click.Choice(['spotify', 'soundcloud']), default='spotify', show_default=True,
              help='service to process (spotify or soundcloud)')
@click.option('--exclude', 'exclude_names', multiple=True, metavar='NAME|ID',
              help='skip a specific playlist (repeatable; applied after scope resolution).')
@click.option('--apply', is_flag=True, help='do it for real (default is a preview).')
@click.option('--format', 'format_opt', default='mp3', show_default=True,
              help='audio format for the download step.')
@click.option('--bitrate', 'bitrate_opt', default='320k', show_default=True, help='audio bitrate.')
@click.option('--cookies-file', 'cookies_file', help='Netscape format cookie file for Spotify download.')
@click.option('--pre-skip-existing', is_flag=True, help='skip downloading existing files.')
@click.option('--retries', 'retries', default=0, show_default=True, type=int, help='number of download retries.')
@click.option('--verbose', is_flag=True, help='verbose output.')
def process_unmatched_cmd(archive_path_opt, playlists_path_opt, exports_dir_opt, service,
                         exclude_names, apply, format_opt, bitrate_opt, cookies_file,
                         pre_skip_existing, retries, verbose):
    """process unmatched tracks: refresh playlists → download missing → import."""
    result = run_process_unmatched(
        archive_path_opt=archive_path_opt,
        playlists_path_opt=playlists_path_opt,
        exports_dir_opt=exports_dir_opt,
        service=service,
        exclude_names=list(exclude_names),
        apply=apply,
        format=format_opt,
        bitrate=bitrate_opt,
        cookies_file=cookies_file,
        pre_skip_existing=pre_skip_existing,
        retries=retries,
        verbose=verbose
    )
    if not result['ok']:
        sys.exit(1)


@core.command('sync')
@click.option('-p', '--playlist', 'names', multiple=True, metavar='NAME|ID',
              help='sync a specific playlist by name or spotify id (repeatable; default: all owned).')
@click.option('--covers', is_flag=True, help='download each playlist cover to <name>.jpg.')
@click.option('--exclude', 'exclude_opt', multiple=True, metavar='NAME|ID',
              help='skip a specific playlist (repeatable; applied after scope resolution).')
@click.option('--verbose', is_flag=True, help='print every match decision.')
@click.option('--playlists-path', 'playlists_path_opt', help='PLAYLISTS_PATH override.')
@click.option('--archive-path', 'archive_path_opt', help='ARCHIVE_PATH (crate root) override.')
@click.option('--exports-dir', 'exports_dir_opt', help='exports dir override.')
def sync_cmd(names, exclude_opt, covers, verbose, playlists_path_opt, archive_path_opt, exports_dir_opt):
    """rescrape spotify + rebuild every (or named) playlist's .m3u8."""
    try:
        run_sync(
            names=list(names), exclude_names=list(exclude_opt), covers=covers, verbose=verbose,
            playlists_path=playlists_path_opt, archive_path=archive_path_opt,
            exports_dir=exports_dir_opt,
        )
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    core()