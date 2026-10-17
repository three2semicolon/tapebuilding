"""organize.beets_import - two-pass beets importer:
  pass 1 - album mode:    groups multi-track albums, moves to albums/Artist - Album/
  pass 2 - singles mode:  remaining loose tracks move to singles/Artist - Title

when running both passes on a crate root like <crate>/unorganized whose layout
is "loose tracks at the root + ready-made album folders under albums/", the
album pass auto-targets <input>/albums (so each folder is one album) and the
singles pass sweeps <input> for the leftover loose files. running both passes on
a flat directory imports everything as one giant album - avoid that by keeping
album folders under an albums/ subdir (or use --pass to target a specific subtree).

cli.py owns argument parsing / exit codes; run_import() below is the plain,
import-safe entry point (also what organize.cli calls). organize.preimport's
stage() is called directly here, not through preimport's own cli - so this
doesn't shell out or depend on preimport's argument parsing at all.

usage (via organize's cli):
  uv run organize import -i <crate>/unorganized -o <crate>
  uv run organize import -i ... -o ... --dry-run
  uv run organize import -i ... -o ... --pass albums   # album pass only
  uv run organize import -i ... -o ... --pass singles  # singles pass only
  uv run organize import --export-csv                   # dump library to csv
"""

import os
import subprocess
import sys
import csv

from lib.paths import resolve as resolve_path, config_path
from lib.tags import EXTENSIONS


def _beets_cmd(output_dir, extra_args):
    """build a beet command pointing at our config."""
    config = config_path()
    library = os.path.join(output_dir, 'beets.db')
    return [
        sys.executable, '-m', 'beets',
        '--config', config,
        '--directory', output_dir,
        '--library', library,
    ] + extra_args


def _resolve_albums_input(input_dir):
    """pass 1 target: <input>/albums if it exists (each folder is one album),
    else <input> itself. lets you point the importer at a crate root whose
    album folders live under an albums/ subdir and still get one-folder-per-album
    grouping instead of beets treating the whole root as one album."""
    albums_subdir = os.path.join(input_dir, 'albums')
    if os.path.isdir(albums_subdir):
        return albums_subdir
    return input_dir


def _album_pass_target(input_dir, preimport_ran, staged_folders):
    """where (if anywhere) the album pass should point.

    when preimport staged the drop, import only <input>/albums/ - the new album
    folders staging created - and only if it actually holds some. never let the
    album pass fall through to <input>/ itself when preimport ran: a flat dir of
    loose singletons would be grouped by beets as one bogus multi-track album.
    empty staging (all stray tracks merged into existing crate albums, or only
    singletons present) returns None -> the dispatch skips the album pass.

    without preimport (--no-preimport), fall back to the legacy resolution."""
    if preimport_ran:
        if not staged_folders:
            return None
        return os.path.join(input_dir, 'albums')
    return _resolve_albums_input(input_dir)


def _warn_singles_after_albums(input_dir):
    """if the albums/ subdir still has audio files, a singles-only run would
    import those multi-track albums track-by-track into singles/ - usually not
    what you want. warn loudly rather than guessing."""
    albums_subdir = os.path.join(input_dir, 'albums')
    if not os.path.isdir(albums_subdir):
        return
    has_audio = any(
        f.lower().endswith(EXTENSIONS)
        for _0, _1, files in os.walk(albums_subdir) for f in files
    )
    if has_audio:
        print(
            f"warning: {albums_subdir} still contains audio files. the singles "
            f"pass is recursive and will import them as singletons (one per track). "
            f"run the album pass first (--pass albums) so they move to albums/, "
            f"or point -i directly at the loose files."
        )


def run_album_pass(input_dir, output_dir, dry_run=False, timid=False):
    """pass 1: import as albums. beets groups tracks by album and matches
    against musicbrainz. moves matched files to albums/Artist - Album/."""
    print(f"\n{'[dry run] ' if dry_run else ''}=== pass 1: album import ===")
    print(f"  input : {input_dir}")
    print(f"  output: {output_dir}")

    args = ['import']
    if dry_run:
        args.append('--pretend')
    if timid:
        # timid mode: only auto-accept very confident matches, prompt on others
        args.extend(['--timid'])
    else:
        # default: auto-accept strong matches, skip anything uncertain
        args.extend(['--quiet'])

    args.append(input_dir)
    cmd = _beets_cmd(output_dir, args)

    print(f"  running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, check=False)
    return result.returncode == 0


def run_singles_pass(input_dir, output_dir, dry_run=False):
    """pass 2: import remaining files as singletons (no album grouping).
    moves to singles/Artist - Title."""
    print(f"\n{'[dry run] ' if dry_run else ''}=== pass 2: singles import ===")
    print(f"  input : {input_dir}")
    print(f"  output: {output_dir}")

    args = ['import', '--singletons']
    if dry_run:
        args.append('--pretend')
    else:
        args.append('--quiet')

    args.append(input_dir)
    cmd = _beets_cmd(output_dir, args)

    print(f"  running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, check=False)
    return result.returncode == 0


def export_library_csv(output_dir, csv_path=None):
    """dump the full beets library to a csv file."""
    if csv_path is None:
        csv_path = os.path.join(output_dir, 'library.csv')

    print(f"\nexporting library index to {csv_path}...")

    # beet ls with format string outputs one line per track
    fmt = '$artist\t$albumartist\t$album\t$track\t$title\t$year\t$path'
    args = ['ls', '-f', fmt]
    cmd = _beets_cmd(output_dir, args)

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"error exporting library: {result.stderr}")
        return False

    lines = [line for line in result.stdout.strip().split('\n') if line.strip()]
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['artist', 'albumartist', 'album', 'track', 'title', 'year', 'path'])
        for line in lines:
            writer.writerow(line.split('\t'))

    print(f"exported {len(lines)} tracks to {csv_path}")
    return True


def print_library_stats(output_dir):
    """print a quick summary of what's in the beets library."""
    args = ['ls', '-f', '$album']
    cmd = _beets_cmd(output_dir, args)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return

    lines = [line for line in result.stdout.strip().split('\n') if line.strip()]
    albums = set(lines)
    print("\nlibrary summary:")
    print(f"  tracks : {len(lines)}")
    print(f"  albums : {len(albums)}")


def _validate_and_setup_input(input_dir, output_dir):
    """Validate input directory and resolve output directory.

    Args:
        input_dir: Input directory path
        output_dir: Output directory path (can be None)

    Returns:
        Tuple of (resolved_input_dir, resolved_output_dir) on success,
        or error dict on failure
    """
    resolved_output_dir = output_dir or resolve_path('ARCHIVE_PATH', required=True)

    if not os.path.exists(input_dir):
        print(f"error: input directory not found: {input_dir}")
        return {'ok': False, 'error': 'Input directory not found'}

    return input_dir, resolved_output_dir


def _handle_preimport_staging(input_dir, output_dir, dry_run, no_preimport,
                              no_merge_existing, verbose, only_pass):
    """Handle pre-import staging if needed.

    Args:
        input_dir: Input directory path
        output_dir: Output directory path
        dry_run: Whether to run in dry-run mode
        no_preimport: Whether to skip preimport
        no_merge_existing: Whether to skip merging existing folders
        verbose: Whether to run in verbose mode
        only_pass: Which pass to run ('albums', 'singles', or None for both)

    Returns:
        Tuple of (merged_folders, staged_folders, import_report, preimport_ran)
    """
    merged_folders = []
    staged_folders = []
    import_report = None
    preimport_ran = (not no_preimport and input_dir and only_pass != 'singles')

    if preimport_ran:
        if os.path.abspath(input_dir) == os.path.abspath(output_dir):
            print("preimport: input is the crate root - stage a subfolder "
                  "(e.g. crate/unorganized), skipping staging")
            preimport_ran = False
        else:
            from organize.preimport import stage as stage_drop
            print("\n=== pre-import staging ===")
            import_report = stage_drop(input_dir, output_dir,
                                       apply=not dry_run,
                                       merge_existing=not no_merge_existing,
                                       verbose=verbose)
            merged_folders = list(import_report.get('merged_folders', []))
            staged_folders = list(import_report.get('staged_folders', []))

    return merged_folders, staged_folders, import_report, preimport_ran


def _should_run_album_pass(only_pass, preimport_ran, staged_folders):
    """Determine if album pass should run based on parameters.

    Args:
        only_pass: Which pass to run ('albums', 'singles', or None for both)
        preimport_ran: Whether preimport was executed
        staged_folders: List of folders staged during preimport

    Returns:
        True if album pass should run, False otherwise
    """
    if only_pass == 'albums':
        return True
    elif only_pass == 'singles':
        return False
    else:  # both passes
        return preimport_ran and bool(staged_folders)


def _run_album_pass_if_needed(target, output_dir, dry_run, timid):
    """Run album pass if target is specified.

    Args:
        target: Target directory for album pass (None to skip)
        output_dir: Output directory path
        dry_run: Whether to run in dry-run mode
        timid: Whether to run in timid mode

    Returns:
        Boolean success status
    """
    if target is None:
        print("\n=== album pass skipped (nothing staged to import) ===")
        return True  # Skipping counts as success

    return run_album_pass(target, output_dir, dry_run, timid)


def _run_singles_pass_if_needed(input_dir, output_dir, dry_run):
    """Run singles pass if needed (with warning for albums-after-singles case).

    Args:
        input_dir: Input directory path
        output_dir: Output directory path
        dry_run: Whether to run in dry-run mode

    Returns:
        Boolean success status
    """
    _warn_singles_after_albums(input_dir)
    return run_singles_pass(input_dir, output_dir, dry_run)


def _handle_post_import_actions(output_dir, dry_run, merged_folders):
    """Handle post-import actions like stats, CSV export, and merge notifications.

    Args:
        output_dir: Output directory path
        dry_run: Whether to run in dry-run mode
        merged_folders: List of folders that were merged during preimport
    """
    if not dry_run:
        print_library_stats(output_dir)
        export_library_csv(output_dir)

        if merged_folders:
            print("\nnote: tracks merged into existing album folders are on disk "
                  "but not in beets.db yet (beets skipped them as duplicates). "
                  "index them with:\n  uv run organize cleanup --rebuild-db")


def _construct_result(success, import_report):
    """Construct the final result dictionary.

    Args:
        success: Whether the import was successful
        import_report: Import report from preimport staging (can be None)

    Returns:
        Result dictionary with success status and optional import report
    """
    result = {'ok': success}
    if import_report is not None:
        result['import_report'] = import_report
    return result


def run_import(input_dir, output_dir=None, dry_run=False, only_pass=None,
               timid=False, no_preimport=False, no_merge_existing=False,
               verbose=False):
    """the two-pass import orchestration that used to live in main() - plain
    function so cli.py (and anything else) can call it directly without
    going through argparse. returns a structured result with success status
    and detailed information including import leftovers.

    output_dir resolution is required, no fallback - deliberately calls
    lib.paths.resolve('ARCHIVE_PATH', required=True) directly instead of
    going through lib.paths.archive_path()'s convenience default
    (~/music/tapebuilding). run_import() moves and renames files just like
    organize.cleanup's regroup policy, so it now matches
    organize.cleanup.resolve_crate()'s reasoning exactly: silently landing
    on a guessed path instead of erroring is the wrong failure mode for
    anything that moves files on disk.
    """
    # Validate and setup input/output directories
    setup_result = _validate_and_setup_input(input_dir, output_dir)
    if isinstance(setup_result, dict) and not setup_result.get('ok', True):
        return setup_result  # Return error dict

    validated_input_dir, resolved_output_dir = setup_result

    if dry_run:
        print("dry run - no files will be moved")

    # Handle pre-import staging
    merged_folders, staged_folders, import_report, preimport_ran = \
        _handle_preimport_staging(validated_input_dir, resolved_output_dir, dry_run,
                                 no_preimport, no_merge_existing, verbose, only_pass)

    # Determine execution flow based on only_pass parameter
    success = True
    if only_pass == 'albums':
        target = _album_pass_target(validated_input_dir, preimport_ran, staged_folders)
        success = _run_album_pass_if_needed(target, resolved_output_dir, dry_run, timid)
    elif only_pass == 'singles':
        success = _run_singles_pass_if_needed(validated_input_dir, resolved_output_dir, dry_run)
    else:
        # Both passes
        target = _album_pass_target(validated_input_dir, preimport_ran, staged_folders)
        ok1 = _run_album_pass_if_needed(target, resolved_output_dir, dry_run, timid)
        ok2 = _run_singles_pass_if_needed(validated_input_dir, resolved_output_dir, dry_run)
        success = ok1 and ok2

    # Handle post-import actions
    _handle_post_import_actions(resolved_output_dir, dry_run, merged_folders)

    # Construct and return final result
    return _construct_result(success, import_report)
