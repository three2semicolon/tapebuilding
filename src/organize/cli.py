"""organize.cli - click group + dispatch for the organize package.

same split as download.cli: this file owns option parsing and exit codes;
the actual logic lives in plain, import-safe functions in the sibling
modules (cleanup.py's run_cleanup(), preimport.py's stage(),
beets_import.py's run_import()/export_library_csv()) that never call
sys.exit() themselves.

pyproject.toml entry point:
    organize = "organize.cli:organize"
"""

import os
import sys

import click
from dotenv import load_dotenv

from lib.paths import archive_path
from organize.cleanup import resolve_crate, run_cleanup
from organize.preimport import stage
from organize.beets_import import run_import, export_library_csv

load_dotenv()


@click.group()
def organize():
    """crate regrouping (cleanup), pre-import staging, and the two-pass
    beets importer for the tapebuilding project."""


# --- cleanup -------------------------------------------------------------

@organize.command('cleanup')
@click.option('--crate', type=click.Path(), help='crate root (default: ARCHIVE_PATH in .env).')
@click.option('--apply', is_flag=True, help='actually move files + write tags (default: dry-run).')
@click.option('--no-tag-write', is_flag=True, help='with --apply: do not rewrite albumartist tags.')
@click.option('--rebuild-db', 'rebuild_db_flag', is_flag=True,
              help='with --apply: rebuild beets.db from the reorganized crate.')
@click.option('--verbose', is_flag=True, help='print every planned move.')
def cleanup_cmd(crate, apply, no_tag_write, rebuild_db_flag, verbose):
    """reorganize the beets crate into proper albums and singles."""
    try:
        run_cleanup(crate=crate, apply=apply, no_tag_write=no_tag_write,
                    rebuild_db_flag=rebuild_db_flag, verbose=verbose)
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


# --- preimport ----------------------------------------------------------

@organize.command('preimport')
@click.option('-i', '--input', 'input_dir', type=click.Path(),
              help='unorganized root (default: <crate>/unorganized).')
@click.option('-o', '--crate', '--output', 'crate', type=click.Path(),
              help='crate root (default: ARCHIVE_PATH in .env).')
@click.option('--apply', is_flag=True, help='stage folders + write tags (default: dry-run).')
@click.option('--no-merge-existing', is_flag=True,
              help="don't merge incoming tracks into existing crate album folders.")
@click.option('--no-tag-write', is_flag=True, help='with --apply: do not rewrite albumartist tags.')
@click.option('--verbose', is_flag=True, help='print every planned move.')
def preimport_cmd(input_dir, crate, apply, no_merge_existing, no_tag_write, verbose):
    """stage unorganized/ so the beets importer does the right thing."""
    try:
        resolved_crate = resolve_crate(crate)
    except ValueError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)

    resolved_input = input_dir or os.path.join(resolved_crate, 'unorganized')
    if not os.path.isdir(resolved_input):
        click.echo(f"error: input directory not found: {resolved_input}", err=True)
        sys.exit(1)

    stage(resolved_input, resolved_crate, apply=apply,
          merge_existing=not no_merge_existing,
          verbose=verbose, no_tag_write=no_tag_write)


# --- import (two-pass beets importer) ------------------------------------

@organize.command('import')
@click.option('--input', '-i', 'input_dir', type=click.Path(),
              help='input directory of unorganized files.')
@click.option('--output', '-o', 'output_dir', type=click.Path(),
              help='output/library root (defaults to ARCHIVE_PATH).')
@click.option('--dry-run', '-n', is_flag=True,
              help='preview what beets would do without moving any files.')
@click.option('--pass', 'only_pass', type=click.Choice(['albums', 'singles']),
              help='run only one pass (default: run both).')
@click.option('--timid', is_flag=True,
              help='prompt on uncertain matches instead of skipping them.')
@click.option('--no-preimport', is_flag=True,
              help='skip the pre-import staging step (raw two-pass beets).')
@click.option('--no-merge-existing', is_flag=True,
              help="don't merge incoming tracks into existing crate album folders.")
@click.option('--verbose', '-v', is_flag=True,
              help='print every staging move + the beets commands.')
@click.option('--export-csv', 'export_csv', is_flag=True,
              help='export library index to library.csv and exit.')
@click.option('--csv-path', 'csv_path', type=click.Path(),
              help='custom path for --export-csv output.')
def import_cmd(input_dir, output_dir, dry_run, only_pass, timid,
               no_preimport, no_merge_existing, verbose, export_csv, csv_path):
    """two-pass beets importer: albums then singletons."""
    resolved_output = output_dir or archive_path()

    if export_csv:
        success = export_library_csv(resolved_output, csv_path)
        sys.exit(0 if success else 1)

    if not input_dir:
        click.echo("error: --input required for import", err=True)
        sys.exit(1)

    success = run_import(
        input_dir,
        output_dir=output_dir,
        dry_run=dry_run,
        only_pass=only_pass,
        timid=timid,
        no_preimport=no_preimport,
        no_merge_existing=no_merge_existing,
        verbose=verbose,
    )
    if not success:
        sys.exit(1)


if __name__ == '__main__':
    organize()
