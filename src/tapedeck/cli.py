"""tapedeck.cli - click entry point + dispatch for the tapedeck package.

same split as download.cli / organize.cli / playlists.cli: this file owns
option parsing and exit codes; the actual logic lives in tapedeck.deck's
plain, import-safe functions (load_tapedeck / unload_tapedeck /
list_tapedeck), none of which call sys.exit() themselves.

pyproject.toml entry point:
    tapedeck = "tapedeck.cli:tapedeck"

deviation from the old argparse version: `unload` previously accepted a
suppressed, unused `--overwrite` and `--exports-dir` (kept only "for parity"
with `load`'s parser, per the old file's comments - never read by _unload).
Dropped here rather than carried forward as dead click options.
"""

import sys

import click
from dotenv import load_dotenv

from tapedeck.deck import KINDS, load_tapedeck, unload_tapedeck, list_tapedeck

load_dotenv()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


@click.group('tapedeck')
def tapedeck():
    """load / list / unload the rotation crate into the tapedeck."""


@tapedeck.command('load')
@click.argument('kind', type=click.Choice(KINDS))
@click.argument('specs', nargs=-1, required=True, metavar='SPEC...')
@click.option('--apply', is_flag=True, help='actually copy/link (default is a dry-run preview).')
@click.option('--link', is_flag=True, help='hardlink instead of copy (same volume only).')
@click.option('--overwrite', is_flag=True, help='replace an existing dst instead of skipping.')
@click.option('--reindex', is_flag=True, help='rebuild the cached crate index first (song/album-by-name).')
@click.option('--verbose', is_flag=True, help='print every file action.')
@click.option('--archive-path', 'archive_path_opt', help='ARCHIVE_PATH (crate root) override.')
@click.option('--tapedeck-path', 'tapedeck_path_opt', help='TAPEDECK_PATH override.')
@click.option('--playlists-path', 'playlists_path_opt', help='PLAYLISTS_PATH override.')
@click.option('--exports-dir', 'exports_dir_opt', help='exports dir override (cached index sidecar).')
def load_cmd(kind, specs, apply, link, overwrite, reindex, verbose,
            archive_path_opt, tapedeck_path_opt, playlists_path_opt, exports_dir_opt):
    """stage albums/songs/soundtracks/playlists into the tapedeck."""
    try:
        load_tapedeck(
            kind, list(specs), apply=apply, link=link, overwrite=overwrite,
            reindex=reindex, verbose=verbose, archive_path=archive_path_opt,
            tapedeck_path=tapedeck_path_opt, playlists_path=playlists_path_opt,
            exports_dir=exports_dir_opt,
        )
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


@tapedeck.command('unload')
@click.argument('kind', type=click.Choice(KINDS))
@click.argument('specs', nargs=-1, required=True, metavar='SPEC...')
@click.option('--apply', is_flag=True, help='actually remove (default is a dry-run preview).')
@click.option('--verbose', is_flag=True, help='print every file action.')
@click.option('--archive-path', 'archive_path_opt', help='ARCHIVE_PATH (crate root) override.')
@click.option('--tapedeck-path', 'tapedeck_path_opt', help='TAPEDECK_PATH override.')
@click.option('--playlists-path', 'playlists_path_opt', help='PLAYLISTS_PATH override.')
def unload_cmd(kind, specs, apply, verbose,
              archive_path_opt, tapedeck_path_opt, playlists_path_opt):
    """remove albums/songs/soundtracks/playlists from the tapedeck."""
    try:
        unload_tapedeck(
            kind, list(specs), apply=apply, verbose=verbose,
            archive_path=archive_path_opt, tapedeck_path=tapedeck_path_opt,
            playlists_path=playlists_path_opt,
        )
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


@tapedeck.command('list')
@click.option('--kind', 'kind_opt', type=click.Choice(KINDS), help='limit to one subtree.')
@click.option('--tapedeck-path', 'tapedeck_path_opt', help='TAPEDECK_PATH override.')
@click.option('--verbose', is_flag=True, help='per-folder / per-file detail.')
def list_cmd(kind_opt, tapedeck_path_opt, verbose):
    """show what is staged on the tapedeck."""
    try:
        list_tapedeck(kind=kind_opt, tapedeck_path=tapedeck_path_opt, verbose=verbose)
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    tapedeck()
