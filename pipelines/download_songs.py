
"""pipelines/download_songs - download, import, and refresh in one pass.

stitches the three existing clis together, so the real work (and the real
argparse) stays where it always did - this script just runs them in order:

  1. 'spotify'      (download.download_spotify) - spotdl the urls into a drop.
  2. 'beets-import' (organize.beets_import)    - two-pass import of the drop
     into the crate (albums/ + singles/), with preimport staging.
  3. 'playlists'    (playlists.build)          - rebuild the .m3u8s so the new
     tracks resolve; --reindex picks up the just-imported files.

each step shells out via 'python -m', so every child keeps its own argparse,
.env loading, and encoding handling. the default is a dry run: it prints the
exact child commands and runs none of them - zero side effects (so it won't
touch the playlists index sidecar the way '--reindex' would on a real run).
'--apply' runs the chain for real; '--only' restricts it to the named step(s).
for a step's own detailed preview - beets' file-by-file plan or the playlist
matcher's counts - run that child directly ('beets-import --dry-run', or
'playlists' without '--apply').

usage:
  uv run pipelines/download_songs.py urls.txt --apply                       # full pass
  uv run pipelines/download_songs.py urls.txt --apply --archive-path Y:/music/crate
  uv run pipelines/download_songs.py "https://open.spotify.com/track/..." --apply  # one url
  uv run pipelines/download_songs.py urls.txt --apply --only download        # download only
  uv run pipelines/download_songs.py --apply --only playlists               # just refresh, no source
"""

import argparse
import os
import subprocess
import sys
import tempfile

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

STEPS = ('download', 'import', 'playlists')


def _looks_like_url(s):
    return s.startswith(('http://', 'https://', 'spotify:')) or 'open.spotify.com' in s


def _resolve_source(source):
    """return a url-file path the 'spotify' cli accepts. accepts an existing
    file/dir, or a bare spotify url (written to a temp one-line .txt). returns
    (path, tmp_to_unlink) so the caller can clean up; (None, None) on bad input."""
    if source and os.path.exists(source):
        return source, None
    if source and _looks_like_url(source):
        tmp = tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8')
        tmp.write(source.strip() + '\n')
        tmp.close()
        return tmp.name, tmp.name
    return None, None


def _run(cmd, apply, verbose):
    """print + run a child cli. dry run prints the command and returns ok; the
    children own their own dry handling, so apply/dry flags are already baked
    into 'cmd' by the caller."""
    rendered = ' '.join(cmd)
    if verbose or not apply:
        print(f"  $ {rendered}")
    if not apply:
        print("  (skipped: dry run - re-run with --apply)")
        return True
    sys.stdout.flush()
    return subprocess.run(cmd).returncode == 0


def main():
    sys.stdout.reconfigure(encoding='utf-8')  # non-ascii artist names on windows
    sys.stderr.reconfigure(encoding='utf-8')

    p = argparse.ArgumentParser(description='download, import, and refresh in one pass')
    p.add_argument('source', nargs='?',
                   help='path to a .txt/.csv of urls (or a dir of .csv), or a single spotify url')
    p.add_argument('--apply', action='store_true',
                   help='do it for real (default: dry run)')
    p.add_argument('--archive-path', help='crate root (default: $ARCHIVE_PATH)')
    p.add_argument('--input', '-i', dest='drop',
                   help='staging drop for downloads (default: <crate>/unorganized)')
    p.add_argument('--only', action='append', choices=STEPS,
                   help='run only this step (repeatable); default: all three in order')
    p.add_argument('--format', default='mp3', help='audio format for the download step (default: mp3)')
    p.add_argument('--bitrate', default='320k', help='audio bitrate (default: 320k)')
    p.add_argument('--verbose', action='store_true',
                   help='echo each sub-command and forward --verbose to the children')
    args = p.parse_args()

    crate = args.archive_path or os.getenv('ARCHIVE_PATH') or os.getenv('archive_path')
    if not crate:
        print("error: --archive-path or ARCHIVE_PATH in .env required", file=sys.stderr)
        sys.exit(1)
    drop = args.drop or os.path.join(crate, 'unorganized')

    selected = args.only or list(STEPS)
    ordered = [s for s in STEPS if s in selected]   # fixed workflow order regardless of --only order

    print(f"crate  : {crate}")
    print(f"drop   : {drop}")
    print(f"steps  : {' -> '.join(ordered)}")
    print(f"mode   : {'apply' if args.apply else 'dry run (prints commands, runs nothing)'}")
    print()

    tmp_path = None
    error = False

    # step 1: download - the 'spotify' cli drops loose files into <drop>.
    if 'download' in ordered:
        print("=== step 1: download (spotify) ===")
        if not args.source:
            print("  error: the download step needs a source (url file/dir, or a single spotify url)")
            error = True
        else:
            url_file, tmp_path = _resolve_source(args.source)
            if url_file is None:
                print(f"  error: source not found and not a spotify url: {args.source}")
                error = True
            else:
                cmd = [sys.executable, '-m', 'download.download_spotify',
                       '--url-file', url_file, '--output', drop,
                       '--format', args.format, '--bitrate', args.bitrate]
                if args.verbose:
                    cmd.append('--verbose')
                if not _run(cmd, args.apply, args.verbose):
                    error = True
        print()

    # step 2: import - beets_import moves <drop> into albums/ + singles/ and
    # registers it in beets.db.
    if 'import' in ordered:
        print("=== step 2: import (beets-import) ===")
        if not os.path.isdir(drop):
            print(f"  ({drop} does not exist - nothing to import"
                  + (" after a skipped download step)" if 'download' in ordered and not args.apply else ")"))
        else:
            cmd = [sys.executable, '-m', 'organize.beets_import',
                   '--input', drop, '--output', crate]
            if args.verbose:
                cmd.append('--verbose')
            if not _run(cmd, args.apply, args.verbose):
                error = True
        print()

    # step 3: refresh playlists - rebuild the .m3u8s; --reindex so the
    # just-imported files are picked up.
    if 'playlists' in ordered:
        print("=== step 3: refresh playlists ===")
        cmd = [sys.executable, '-m', 'playlists.build',
               '--apply', '--archive-path', crate, '--reindex']
        if args.verbose:
            cmd.append('--verbose')
        if not _run(cmd, args.apply, args.verbose):
            error = True
        print()

    if tmp_path and os.path.exists(tmp_path):
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if error:
        sys.exit(1)
    print("done.")


if __name__ == '__main__':
    main()
