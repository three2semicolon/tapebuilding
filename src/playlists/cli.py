"""playlists.cli - click entry point + dispatch for the playlists package.

same split as download.cli / organize.cli: this file owns option parsing
and exit codes; the actual logic lives in playlists.build.build_playlists(),
a plain, import-safe function that never calls sys.exit() itself.

pyproject.toml entry point:
    playlists = "playlists.cli:playlists"
"""

import sys

import click
from dotenv import load_dotenv

from playlists.build import build_playlists

load_dotenv()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


@click.command('playlists')
@click.option('--apply', is_flag=True, help='write the .m3u8 files (default is a preview).')
@click.option('--all', 'all_playlists', is_flag=True,
              help='build every playlist in playlists.csv (incl. followed/shared).')
@click.option('--mine', is_flag=True,
              help="only your own playlists (default - this flag is only here to error "
                   "clearly if combined with --all, same as the old argparse group).")
@click.option('-p', '--playlist', 'names', multiple=True, metavar='NAME|ID',
              help='build a specific playlist by name or spotify id (repeatable; overrides scope).')
@click.option('--rescrape', is_flag=True,
              help="refresh the spotify csvs first (full export; with -p, only the named playlists).")
@click.option('--covers', is_flag=True,
              help='download each playlist cover to <name>.jpg (needs --rescrape or spotify auth).')
@click.option('--reindex', is_flag=True,
              help='rebuild the local .playlist_index.jsonl sidecar before matching.')
@click.option('--verbose', is_flag=True, help='print every match decision.')
@click.option('-o', '--playlists-path', 'playlists_path_opt', help='PLAYLISTS_PATH override.')
@click.option('--archive-path', 'archive_path_opt', help='ARCHIVE_PATH (crate root) override.')
@click.option('--exports-dir', 'exports_dir_opt', help='exports dir override (default PLAYLISTS_PATH/exports).')
def playlists(apply, all_playlists, mine, names, rescrape, covers, reindex, verbose,
              playlists_path_opt, archive_path_opt, exports_dir_opt):
    """build local .m3u8 playlists from spotify playlists."""
    if mine and all_playlists:
        click.echo("error: --all and --mine are mutually exclusive.", err=True)
        sys.exit(2)

    try:
        build_playlists(
            apply=apply,
            all_playlists=all_playlists,
            names=list(names),
            rescrape=rescrape,
            covers=covers,
            reindex=reindex,
            verbose=verbose,
            playlists_path=playlists_path_opt,
            archive_path=archive_path_opt,
            exports_dir=exports_dir_opt,
        )
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    playlists()
