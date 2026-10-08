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

from download.spotify.spotify_export import extract_playlist_id_from_url
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
@click.option('--exclude', multiple=True, metavar='NAME|ID',
              help='skip a specific playlist (repeatable; applied after scope resolution).')
@click.option('--reindex', is_flag=True,
              help='rebuild the local .playlist_index.jsonl sidecar before matching.')
@click.option('--verbose', is_flag=True, help='print every match decision.')
@click.option('-o', '--playlists-path', 'playlists_path_opt', help='PLAYLISTS_PATH override.')
@click.option('--archive-path', 'archive_path_opt', help='ARCHIVE_PATH (crate root) override.')
@click.option('--exports-dir', 'exports_dir_opt', help='exports dir override (default PLAYLISTS_PATH/exports).')
@click.option('--service', type=click.Choice(['spotify', 'soundcloud']), default='spotify', show_default=True,
              help='service to process (spotify or soundcloud)')
def playlists(apply, all_playlists, mine, names, exclude, rescrape, covers, reindex, verbose,
              playlists_path_opt, archive_path_opt, exports_dir_opt, service):
    """build local .m3u8 playlists from spotify or soundcloud playlists."""
    if mine and all_playlists:
        click.echo("error: --all and --mine are mutually exclusive.", err=True)
        sys.exit(2)

    if names and exclude:
        # check for contradictory -p/--playlist and --exclude on the same playlist
        exclude_ids = set()
        exclude_names_raw = set()
        for token in exclude:
            as_id = extract_playlist_id_from_url(token)
            if len(as_id) >= 16:
                exclude_ids.add(as_id)
            else:
                exclude_names_raw.add(token)
        for token in names:
            as_id = extract_playlist_id_from_url(token)
            if len(as_id) >= 16 and as_id in exclude_ids:
                click.echo(f"error: -p '{token}' and --exclude '{token}' are mutually exclusive.", err=True)
                sys.exit(2)
            if len(as_id) < 16 and token in exclude_names_raw:
                click.echo(f"error: -p '{token}' and --exclude '{token}' are mutually exclusive.", err=True)
                sys.exit(2)

    try:
        build_playlists(
            apply=apply,
            all_playlists=all_playlists,
            names=list(names),
            exclude_names=list(exclude),
            rescrape=rescrape,
            covers=covers,
            reindex=reindex,
            verbose=verbose,
            playlists_path=playlists_path_opt,
            archive_path=archive_path_opt,
            exports_dir=exports_dir_opt,
            service=service,
        )
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    playlists()
