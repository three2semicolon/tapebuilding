"""core.process_unmatched - Process unmatched tracks from playlist refresh.

Workflow:
1. Refresh playlists with rescrape/reindex to generate unmatched CSV
2. Download tracks listed in the unmatched CSV
3. Import the downloaded tracks into the library
"""

import os
from lib.paths import archive_path, playlists_path, exports_dir as resolve_exports_dir
from playlists.build import _spotify_exports_dir, build_playlists
from download.spotify.spotify_download import download_spotify
from organize.beets_import import run_import

def run_process_unmatched(
    archive_path_opt=None,
    playlists_path_opt=None,
    exports_dir_opt=None,
    service='spotify',
    exclude_names=None,
    apply=False,
    format='mp3',
    bitrate='320k',
    cookies_file=None,
    pre_skip_existing=False,
    retries=0,
    verbose=False
):
    """
    Execute the full unmatched tracks processing pipeline.

    Returns:
        dict: {'steps': [{'step', 'ok', 'error', 'skipped'], ...], 'ok': bool}
    """
    # Handle PLAYLISTS_EXCLUDE environment variable as standing default for --exclude
    import os
    env_exclude = os.environ.get('PLAYLISTS_EXCLUDE', '')
    if env_exclude:
        env_exclude_list = [item.strip() for item in env_exclude.split(',') if item.strip()]
        if exclude_names:
            exclude_names = list(exclude_names) + env_exclude_list
        else:
            exclude_names = env_exclude_list

    # Resolve paths (same as in playlists.build)
    playlists_path_resolved = playlists_path_opt or playlists_path()
    exports_dir_resolved = resolve_exports_dir(playlists_path_resolved, exports_dir_opt)

    # Determine service-specific exports directory (same as in playlists.build)
    if service == 'soundcloud':
        service_exports_dir = os.path.join(exports_dir_resolved, 'soundcloud')
    else:  # spotify (default)
        service_exports_dir = _spotify_exports_dir(exports_dir_resolved)

    unorganized_dir = os.path.join((archive_path_opt or archive_path()), 'unorganized')

    # Ensure directories exist
    os.makedirs(unorganized_dir, exist_ok=True)

    results = []

    def record(step, ok, error=None, skipped=False):
        results.append({'step': step, 'ok': ok, 'error': error, 'skipped': skipped})

    crate = archive_path_opt or archive_path()
    print(f"crate        : {crate}")
    print(f"playlists    : {playlists_path_resolved}")
    print(f"unmatched csv: {os.path.join(service_exports_dir, 'unmatched.csv')}")
    print(f"unorganized  : {unorganized_dir}")
    print(f"mode         : {'apply' if apply else 'dry run'}")
    print()

    # Step 1: Refresh playlists to generate unmatched CSV
    print("=== step 1: refresh playlists (rescrape/reindex) ===")
    try:
        # Note: build_playlists always returns True, but we check if unmatched CSV is generated
        build_playlists(
            apply=apply,
            rescrape=True,
            reindex=True,
            names=[],  # No specific names - use scope (owned playlists)
            exclude_names=exclude_names or [],
            service=service,
            archive_path=crate,
            playlists_path=playlists_path_resolved,
            exports_dir=exports_dir_opt,
            verbose=verbose
        )

        # Check if unmatched CSV was created
        unmatched_csv_path = os.path.join(service_exports_dir, 'unmatched.csv')
        if os.path.exists(unmatched_csv_path):
            record('refresh-playlists', True)
            print(f"  generated: {unmatched_csv_path}")
        else:
            record('refresh-playlists', False, error="unmatched CSV not generated")
    except Exception as e:
        record('refresh-playlists', False, error=str(e))
        print(f"  error: {e}")
    print()

    # Step 2: Download from unmatched CSV (if it exists and we're not in dry-run or it exists)
    if 'refresh-playlists' in [r['step'] for r in results if r['ok']]:
        print("=== step 2: download from unmatched CSV ===")
        unmatched_csv_path = os.path.join(service_exports_dir, 'unmatched.csv')
        if not os.path.exists(unmatched_csv_path):
            record('download', False, error="unmatched CSV not found")
        else:
            try:
                # Configure download options
                ok = download_spotify(
                    url_file=unmatched_csv_path,
                    output_dir=unorganized_dir,
                    format=format,
                    bitrate=bitrate,
                    cookies_file=cookies_file,
                    pre_skip_existing=pre_skip_existing,
                    retries=retries,
                    validate_only=not apply,  # Dry run mode
                    debug=verbose
                )
                record('download', ok)
            except Exception as e:
                record('download', False, error=str(e))
                print(f"  error: {e}")
    else:
        record('download', True, skipped=True)  # Skip if previous step failed
    print()

    # Step 3: Import downloaded files
    download_success = any(r['step'] == 'download' and r['ok'] and not r['skipped'] for r in results)
    if download_success:
        print("=== step 3: import downloaded files ===")
        try:
            import_result = run_import(
                input_dir=unorganized_dir,
                output_dir=crate,
                dry_run=not apply,
                verbose=verbose
            )
            ok = import_result.get('ok', False)
            record('import', ok)
        except Exception as e:
            record('import', False, error=str(e))
            print(f"  error: {e}")
    else:
        record('import', True, skipped=True)  # Skip if download failed/skipped
    print()

    # Overall result
    overall_ok = all(r['ok'] for r in results if not r['skipped'])
    print("done." if overall_ok else "completed with errors - see steps above.")
    return {'steps': results, 'ok': overall_ok}