
"""core.download - download, import, and refresh in one pass, in-process.

renamed from pipelines/download_songs.py during the lib/ refactor. same
three-step workflow, same fixed step order, same --apply/dry-run/--only
semantics as the subprocess version - the only thing that changed is the
*mechanism*: each step now calls straight into the already-refactored domain
functions instead of shelling out to `python -m package.module`.

  1. download   - download.spotify_download.download_spotify() for Spotify URLs,
                  download.ytdl.download_ytdl() for other URLs
  2. import     - organize.beets_import.run_import()
  3. playlists  - playlists.build.build_playlists()

what "dry run" means for each step, now that there's no child command to just
print instead of running (this was an explicit open question in TODO.md's
Phase 6 - resolved here, not deferred):
  - download:  download_spotify(..., validate_only=not apply) - a real
    no-op that still does the existence check and prints what *would*
    download, rather than the step being skipped outright.
  - import:    run_import(..., dry_run=not apply) - already a genuine
    pretend mode (beets `--pretend`), used as-is.
  - playlists: build_playlists(apply=apply, ...) - already a genuine
    preview mode (writes nothing), used as-is.
None of the three steps are skipped in dry-run mode anymore; each is called
for real, just in its own no-op mode. This is a deliberate behavior change
from the old subprocess version, which printed the would-be command and ran
nothing at all for every step - worth knowing if anything relied on a dry
run being a true no-op (e.g. the import step's --pretend still talks to
musicbrainz; the download step's validate_only still hits disk for the
existence scan).

verbose -> debug mapping for the download step, confirmed: download.cli's
`spotify` subcommand has no --verbose of its own - its only relevant flag
is --debug, passed straight through as download_spotify(..., debug=debug).
There's no separate old --verbose behavior this could have diverged from;
`debug` is simply the parameter's real name (spotdl/yt-dlp log level), so
forwarding core's --verbose onto it here is the correct analog, not a
guess.

structured returns: download_spotify()/run_import() return a bare bool, and
build_playlists() always returns True regardless of match outcome - none of
the three give real per-step counts today. "Structured results" here means
this module's own per-step {step, ok, error, skipped} summary, not counts
from inside each step. Getting real counts would mean changing the three
domain functions themselves - out of scope for this pass.
"""

import os
import tempfile

from lib.paths import archive_path
from download.spotify.spotify_download import download_spotify
from download.ytdl import download_ytdl
from organize.beets_import import run_import
from playlists.build import build_playlists

STEPS = ('download', 'import', 'playlists')


def _looks_like_url(s):
    return s.startswith(('http://', 'https://', 'spotify:')) or 'open.spotify.com' in s


def _handle_configuration_and_paths(source, apply, archive_path_opt, drop, only, format, bitrate, verbose, clean):
    """Handle configuration and path resolution for the download songs pipeline.

    Args:
        source: Source for download (file/dir, URL, or None)
        apply: Whether to apply changes or just preview
        archive_path_opt: Optional archive path override
        drop: Optional drop directory override
        only: Optional list of steps to run
        format: Audio format for download
        bitrate: Audio bitrate for download
        verbose: Whether to show verbose output
        clean: Whether to clean up temporary files

    Returns:
        tuple: (crate, resolved_drop, selected, ordered)
    """
    crate = archive_path_opt or archive_path()
    resolved_drop = drop or os.path.join(crate, 'unorganized')

    selected = only or list(STEPS)
    ordered = [s for s in STEPS if s in selected]   # fixed workflow order regardless of --only order

    print(f"crate  : {crate}")
    print(f"drop   : {resolved_drop}")
    print(f"steps  : {' -> '.join(ordered)}")
    print(f"mode   : {'apply' if apply else 'dry run (each step runs in its own preview mode)'}")
    print()

    return crate, resolved_drop, selected, ordered


def _download_step(source, resolved_drop, format, bitrate, verbose, ordered, record, apply):
    """Handle the download step of the download songs pipeline.

    Args:
        source: Source for download (file/dir, URL, or None)
        resolved_drop: Path to the drop directory
        format: Audio format for download
        bitrate: Audio bitrate for download
        verbose: Whether to show verbose output
        ordered: List of steps to run in order
        record: Function to record step results
        apply: Whether to apply changes or just preview

    Returns:
        tuple: (tmp_path, updated_apply) - tmp_path for cleanup tracking, apply unchanged
    """
    tmp_path = None
    # step 1: download - spotdl for Spotify URLs, ytdl for others
    if 'download' in ordered:
        print("=== step 1: download ===")
        if not source:
            msg = "the download step needs a source (url file/dir, or a single spotify url)"
            print(f"  error: {msg}")
            record('download', False, error=msg)
        else:
            # Check if source is an existing file/dir
            if os.path.exists(source):
                # Treat existing files as Spotify URL manifest files (preserve existing behavior)
                print(f"  (using existing file/dir as source: {source})")
                try:
                    ok = download_spotify(
                        url_file=source, output_dir=resolved_drop,
                        format=format, bitrate=bitrate,
                        validate_only=not apply, debug=verbose,
                    )
                    record('download', ok)
                except Exception as e:
                    print(f"  error: {e}")
                    record('download', False, error=str(e))
            elif _looks_like_url(source):
                # Handle direct URLs
                if _is_spotify_url(source):
                    # Spotify URL: use spotdl (existing behavior)
                    url_file, tmp_path = _resolve_source(source)
                    if url_file is None:
                        msg = f"failed to resolve Spotify URL: {source}"
                        print(f"  error: {msg}")
                        record('download', False, error=msg)
                    else:
                        try:
                            ok = download_spotify(
                                url_file=url_file, output_dir=resolved_drop,
                                format=format, bitrate=bitrate,
                                validate_only=not apply, debug=verbose,
                            )
                            record('download', ok)
                        except Exception as e:
                            print(f"  error: {e}")
                            record('download', False, error=str(e))
                else:
                    # Non-Spotify URL: use ytdl directly
                    try:
                        ok = download_ytdl(
                            url=source, output_dir=resolved_drop,
                            audio_format=format, audio_quality=bitrate,
                            embed_thumbnail=True, overwrite=False,
                            verbose=verbose, metadata_only=not apply,
                            cookies_from_browser=None, ffmpeg_path=None,
                        )
                        record('download', ok)
                    except Exception as e:
                        print(f"  error: {e}")
                        record('download', False, error=str(e))
            else:
                msg = f"source not found and not a valid URL: {source}"
                print(f"  error: {msg}")
                record('download', False, error=msg)
    return tmp_path, apply


def _import_step(resolved_drop, crate, ordered, record, apply, verbose):
    """Handle the import step of the download songs pipeline.

    Args:
        resolved_drop: Path to the drop directory
        crate: Path to the crate directory
        ordered: List of steps to run in order
        record: Function to record step results
        apply: Whether to apply changes or just preview
        verbose: Whether to show verbose output

    Returns:
        None (results are recorded via the record function)
    """
    # step 2: import - beets_import moves <drop> into albums/ + singles/ and
    # registers it in beets.db.
    if 'import' in ordered:
        print("=== step 2: import (beets-import) ===")
        if not os.path.isdir(resolved_drop):
            if 'download' in ordered and not apply:
                print(f"  ({resolved_drop} does not exist - nothing to import "
                      f"(dry run: the download step above doesn't create files))")
            else:
                print(f"  ({resolved_drop} does not exist - nothing to import)")
            record('import', True, skipped=True)
        else:
            try:
                import_result = run_import(input_dir=resolved_drop, output_dir=crate,
                                          dry_run=not apply, verbose=verbose)
                ok = import_result.get('ok', False)
                record('import', ok)

                # Report import leftovers if available in the structured result
                if 'import_report' in import_result:
                    report = import_result['import_report']
                    leftover_count = report.get('leftover_count', 0)
                    if leftover_count > 0:
                        print(f"  import leftovers: {leftover_count} files")
                        if verbose and 'leftover_paths' in report:
                            for path in report['leftover_paths'][:5]:  # Limit to 5 paths in output
                                print(f"    {os.path.relpath(path, resolved_drop)}")
                        elif not verbose:
                            print("    (use --verbose to see paths)")
            except Exception as e:
                print(f"  error: {e}")
                record('import', False, error=str(e))


def _playlists_step(crate, ordered, record, apply, verbose):
    """Handle the playlists step of the download songs pipeline.

    Args:
        crate: Path to the crate directory
        ordered: List of steps to run in order
        record: Function to record step results
        apply: Whether to apply changes or just preview
        verbose: Whether to show verbose output

    Returns:
        None (results are recorded via the record function)
    """
    # step 3: refresh playlists - rebuild the .m3u8s; reindex so the
    # just-imported files are picked up.
    if 'playlists' in ordered:
        print("=== step 3: refresh playlists ===")
        try:
            ok = build_playlists(apply=apply, archive_path=crate, reindex=True,
                                verbose=verbose)
            record('playlists', ok)
        except Exception as e:
            print(f"  error: {e}")
            record('playlists', False, error=str(e))


def _is_spotify_url(s):
    """Return True if s is a Spotify URL or URI."""
    return s.startswith(('https://open.spotify.com/', 'http://open.spotify.com/', 'spotify:'))


def _resolve_source(source):
    """return a url-file path download_spotify() accepts. accepts an existing
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


def run_download_songs(source=None, apply=False, archive_path_opt=None, drop=None,
                       only=None, format='mp3', bitrate='320k', verbose=False, clean=False):
    """download -> beets-import -> playlists-refresh, in-process. plain,
    import-safe entry point - cli.py resolves click options into these
    kwargs and turns a failed result into an exit code; nothing in here
    calls sys.exit() itself.

    returns {'steps': [{'step', 'ok', 'error', 'skipped'}, ...], 'ok': bool}
    - overall 'ok' is False if any non-skipped step failed or raised.
    """
    # Handle configuration and path resolution
    crate, resolved_drop, selected, ordered = _handle_configuration_and_paths(
        source, apply, archive_path_opt, drop, only, format, bitrate, verbose, clean
    )

    # Initialize tracking variables
    tmp_path = None
    results = []

    def record(step, ok, error=None, skipped=False):
        results.append({'step': step, 'ok': ok, 'error': error, 'skipped': skipped})

    # step 1: download - spotdl for Spotify URLs, ytdl for others
    tmp_path, apply = _download_step(
        source, resolved_drop, format, bitrate, verbose, ordered, record, apply
    )
    print()

    # step 2: import - beets_import moves <drop> into albums/ + singles/ and
    # registers it in beets.db.
    _import_step(
        resolved_drop, crate, ordered, record, apply, verbose
    )
    print()

    # step 3: refresh playlists - rebuild the .m3u8s; reindex so the
    # just-imported files are picked up.
    _playlists_step(
        crate, ordered, record, apply, verbose
    )
    print()

    # Cleanup and final result calculation
    tmp_path = _cleanup_temp_file(tmp_path)
    overall_ok = _calculate_overall_result(results)
    print("done." if overall_ok else "completed with errors - see steps above.")
    return {'steps': results, 'ok': overall_ok}


def _cleanup_temp_file(tmp_path):
    """Clean up temporary file if it exists.

    Args:
        tmp_path: Temporary path to clean up

    Returns:
        None (always returns None for consistency)
    """
    if tmp_path and os.path.exists(tmp_path):
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return None


def _calculate_overall_result(results):
    """Calculate the overall result based on step results.

    Args:
        results: List of step result dictionaries

    Returns:
        bool: True if all non-skipped steps were successful, False otherwise
    """
    return all(r['ok'] for r in results if not r['skipped'])
