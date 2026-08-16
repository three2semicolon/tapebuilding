
"""
two-pass beets importer:
  pass 1 - album mode:    groups multi-track albums, moves to albums/Artist - Album/
  pass 2 - singles mode:  remaining loose tracks move to singles/Artist - Title

when running both passes on a crate root like <crate>/unorganized whose layout
is "loose tracks at the root + ready-made album folders under albums/", the
album pass auto-targets <input>/albums (so each folder is one album) and the
singles pass sweeps <input> for the leftover loose files. running both passes on
a flat directory imports everything as one giant album - avoid that by keeping
album folders under an albums/ subdir (or use --pass to target a specific subtree).

usage:
  uv run python -m organize.beets_import -i <crate>/unorganized -o <crate>
  uv run python -m organize.beets_import -i ... -o ... --dry-run
  uv run python -m organize.beets_import -i ... -o ... --pass albums   # album pass only
  uv run python -m organize.beets_import -i ... -o ... --pass singles  # singles pass only
  uv run python -m organize.beets_import --export-csv                   # dump library to csv
"""

import argparse
import os
import subprocess
import sys
import csv
from dotenv import load_dotenv

load_dotenv()

def _config_path():
    """config.yaml sits alongside this file in organize/."""
    return os.path.join(os.path.dirname(__file__), 'config.yaml')


def _beets_cmd(output_dir, extra_args):
    """build a beet command pointing at our config."""
    config = _config_path()
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
        f.lower().endswith(('.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aac'))
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

    lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
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

    lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
    albums = set(lines)
    print(f"\nlibrary summary:")
    print(f"  tracks : {len(lines)}")
    print(f"  albums : {len(albums)}")


def main():
    parser = argparse.ArgumentParser(
        description='two-pass beets importer: albums then singletons'
    )
    parser.add_argument('--input', '-i', type=str,
                        help='input directory of unorganized files')
    parser.add_argument('--output', '-o', type=str,
                        help='output/library root (defaults to ARCHIVE_PATH)')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='preview what beets would do without moving any files')
    parser.add_argument('--pass', dest='only_pass', choices=['albums', 'singles'],
                        help='run only one pass (default: run both)')
    parser.add_argument('--timid', action='store_true',
                        help='prompt on uncertain matches instead of skipping them')
    parser.add_argument('--no-preimport', action='store_true',
                        help='skip the pre-import staging step (raw two-pass beets)')
    parser.add_argument('--no-merge-existing', action='store_true',
                        help="don't merge incoming tracks into existing crate album folders")
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='print every staging move + the beets commands')
    parser.add_argument('--export-csv', action='store_true',
                        help='export library index to library.csv and exit')
    parser.add_argument('--csv-path', type=str,
                        help='custom path for --export-csv output')

    args = parser.parse_args()

    # resolve output dir from .env if not provided
    output_dir = args.output or os.getenv('ARCHIVE_PATH') or os.getenv('archive_path')
    if not output_dir:
        print("error: --output or ARCHIVE_PATH in .env required")
        sys.exit(1)

    if args.export_csv:
        success = export_library_csv(output_dir, args.csv_path)
        sys.exit(0 if success else 1)

    input_dir = args.input
    if not input_dir:
        print("error: --input required for import")
        sys.exit(1)

    if not os.path.exists(input_dir):
        print(f"error: input directory not found: {input_dir}")
        sys.exit(1)

    if args.dry_run:
        print("dry run - no files will be moved")

    # pre-import staging: regroup <input> into one folder per album and write a
    # canonical albumartist tag into each, so the album pass doesn't split albums
    # by track-artist and the singles pass only gets true singletons. see
    # organize/preimport.py. skipped in singles-only mode (staged folders would
    # otherwise be singleton-imported by the very sweep that follows).
    merged_folders = []
    staged_folders = []
    preimport_ran = (not args.no_preimport and input_dir
                     and args.only_pass != 'singles')
    if preimport_ran:
        if os.path.abspath(input_dir) == os.path.abspath(output_dir):
            print("preimport: input is the crate root - stage a subfolder "
                  "(e.g. crate/unorganized), skipping staging")
            preimport_ran = False
        else:
            from organize.preimport import stage as stage_drop
            print("\n=== pre-import staging ===")
            report = stage_drop(input_dir, output_dir,
                                apply=not args.dry_run,
                                merge_existing=not args.no_merge_existing,
                                verbose=args.verbose)
            merged_folders = list(report.get('merged_folders', []))
            staged_folders = list(report.get('staged_folders', []))

    success = True
    if args.only_pass == 'albums':
        target = _album_pass_target(input_dir, preimport_ran, staged_folders)
        if target is None:
            print("\n=== album pass skipped (nothing staged to import) ===")
        else:
            success = run_album_pass(target, output_dir, args.dry_run, args.timid)
    elif args.only_pass == 'singles':
        _warn_singles_after_albums(input_dir)
        success = run_singles_pass(input_dir, output_dir, args.dry_run)
    else:
        # both passes. album pass imports only what preimport staged under
        # <input>/albums/ (one folder per new album); skip it entirely when
        # staging staged nothing (flat singletons would otherwise form one bogus
        # multi-track album). singles pass sweeps <input> for the loose singletons.
        target = _album_pass_target(input_dir, preimport_ran, staged_folders)
        ok1 = True
        if target is not None:
            ok1 = run_album_pass(target, output_dir, args.dry_run, args.timid)
        else:
            print("\n=== album pass skipped (nothing staged to import) ===")
        ok2 = run_singles_pass(input_dir, output_dir, args.dry_run)
        success = ok1 and ok2

    if not args.dry_run:
        print_library_stats(output_dir)
        export_library_csv(output_dir)

        if merged_folders:
            print("\nnote: tracks merged into existing album folders are on disk "
                  "but not in beets.db yet (beets skipped them as duplicates). "
                  "index them with:\n  uv run python -m organize.cleanup --rebuild-db")

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
