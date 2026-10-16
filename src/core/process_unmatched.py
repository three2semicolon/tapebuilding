"""core.process_unmatched - Process unmatched tracks from playlist refresh.

Workflow:
1. Refresh playlists with rescrape/reindex to generate unmatched CSV
2. Download tracks listed in the unmatched CSV
3. Import the downloaded tracks into the library
4. Refresh playlists (reindex only) to sync with updated library
"""

import os
from lib.paths import archive_path, playlists_path, exports_dir as resolve_exports_dir
from playlists.build import _spotify_exports_dir, build_playlists
from download.spotify.spotify_download import download_spotify
from organize.beets_import import run_import

def _handle_playlists_exclude(exclude_names):
    """Handle PLAYLISTS_EXCLUDE environment variable as standing default for --exclude."""
    env_exclude = os.environ.get('PLAYLISTS_EXCLUDE', '')
    if env_exclude:
        env_exclude_list = [item.strip() for item in env_exclude.split(',') if item.strip()]
        if exclude_names:
            return list(exclude_names) + env_exclude_list
        else:
            return env_exclude_list
    # else: exclude_names remains as passed (could be None)
    return exclude_names


def _handle_download_pre_skip_existing(pre_skip_existing):
    """Handle DOWNLOAD_PRE_SKIP_EXISTING environment variable as default for --pre-skip-existing."""
    env_pre_skip = os.environ.get('DOWNLOAD_PRE_SKIP_EXISTING', '')
    if env_pre_skip:
        # Convert to boolean - common true values
        if env_pre_skip.lower() in ('true', '1', 'yes', 'on'):
            env_pre_skip_bool = True
        elif env_pre_skip.lower() in ('false', '0', 'no', 'off'):
            env_pre_skip_bool = False
        else:
            # Default to False if unrecognized value
            env_pre_skip_bool = False
        if pre_skip_existing is False:  # Only apply env var if still at default (not explicitly set via command line)
            return env_pre_skip_bool
    return pre_skip_existing


def _handle_download_cookies_file(cookies_file):
    """Handle DOWNLOAD_COOKIES_FILE environment variable as default for --cookies-file."""
    env_cookies_file = os.environ.get('DOWNLOAD_COOKIES_FILE', '')
    if env_cookies_file:
        if cookies_file is None:  # Only apply env var if not explicitly set via command line
            return env_cookies_file
    return cookies_file


def _handle_download_retries(retries):
    """Handle DOWNLOAD_RETRIES environment variable as default for --retries."""
    env_retries = os.environ.get('DOWNLOAD_RETRIES', '')
    if env_retries:
        try:
            env_retries_int = int(env_retries)
            if retries == 0:  # Only apply env var if still at default (not explicitly set via command line)
                return env_retries_int
        except ValueError:
            # If not a valid integer, ignore the environment variable
            pass
    return retries


def _handle_environment_variables(exclude_names, pre_skip_existing, cookies_file, retries):
    """Handle environment variables that serve as defaults for command-line options.

    Processes PLAYLISTS_EXCLUDE, DOWNLOAD_PRE_SKIP_EXISTING, DOWNLOAD_COOKIES_FILE,
    and DOWNLOAD_RETRIES environment variables, applying them only when the
    corresponding parameter is at its default value.

    Returns:
        tuple: (processed_exclude_names, processed_pre_skip_existing,
                processed_cookies_file, processed_retries)
    """
    exclude_names = _handle_playlists_exclude(exclude_names)
    pre_skip_existing = _handle_download_pre_skip_existing(pre_skip_existing)
    cookies_file = _handle_download_cookies_file(cookies_file)
    retries = _handle_download_retries(retries)

    return exclude_names, pre_skip_existing, cookies_file, retries


def _refresh_playlists_step(service_exports_dir, skip_initial_playlist_refresh, apply, verbose,
                           exclude_names, service, crate, playlists_path_resolved, exports_dir_opt, record):
    """Handle the refresh playlists step of the unmatched tracks processing pipeline.

    Args:
        service_exports_dir: Path to service-specific exports directory
        skip_initial_playlist_refresh: Whether to skip the initial playlist refresh
        apply: Whether to apply changes or just show what would be done
        verbose: Whether to show verbose output
        exclude_names: List of names to exclude from processing
        service: Service name ('spotify' or 'soundcloud')
        crate: Path to the crate/archive directory
        playlists_path_resolved: Resolved playlists path
        exports_dir_opt: Optional exports directory override
        record: Function to record step results

    Returns:
        None (results are recorded via the record function)
    """
    if skip_initial_playlist_refresh:
        print("=== step 1: refresh playlists (rescrape/reindex) [SKIPPED] ===")
        # When skipping, we still need to check if unmatched CSV exists
        unmatched_csv_path = os.path.join(service_exports_dir, 'unmatched.csv')
        if os.path.exists(unmatched_csv_path):
            record('refresh-playlists', True, skipped=True)
            print(f"  using existing unmatched CSV: {unmatched_csv_path}")
        else:
            record('refresh-playlists', False, error="unmatched CSV not found and initial refresh was skipped")
    else:
        print("=== step 1: refresh playlists (rescrape/reindex) ===")
        try:
            # Note: build_playlists always returns True, but we check if unmatched CSV is generated
            build_playlists(
                apply=apply,
                rescrape=True,  # Rescrape from Spotify to get latest data
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
            else:
                record('refresh-playlists', False, error="unmatched CSV not generated")
        except Exception as e:
            record('refresh-playlists', False, error=str(e))


def _resolve_paths(archive_path_opt, playlists_path_opt, exports_dir_opt, service):
    """Resolve paths for the unmatched tracks processing pipeline.

    Resolves archive_path, playlists_path, exports_dir, service_exports_dir,
    and unorganized_dir based on the provided options and defaults.

    Args:
        archive_path_opt: Optional archive path override
        playlists_path_opt: Optional playlists path override
        exports_dir_opt: Optional exports directory override
        service: Service name ('spotify' or 'soundcloud')

    Returns:
        tuple: (playlists_path_resolved, exports_dir_resolved, service_exports_dir, unorganized_dir, crate)
    """
    # Resolve paths (same as in playlists.build)
    playlists_path_resolved = playlists_path_opt or playlists_path()
    exports_dir_resolved = resolve_exports_dir(playlists_path_resolved, exports_dir_opt)

    # Determine service-specific exports directory (same as in playlists.build)
    if service == 'soundcloud':
        service_exports_dir = os.path.join(exports_dir_resolved, 'soundcloud')
    else:  # spotify (default)
        service_exports_dir = _spotify_exports_dir(exports_dir_resolved)

    unorganized_dir = os.path.join((archive_path_opt or archive_path()), 'unorganized')
    crate = archive_path_opt or archive_path()

    return playlists_path_resolved, exports_dir_resolved, service_exports_dir, unorganized_dir, crate


def _download_step(skip_initial_playlist_refresh, service_exports_dir, unorganized_dir, format, bitrate,
                  cookies_file, pre_skip_existing, retries, apply, verbose, manual, record, results):
    """Handle the download step of the unmatched tracks processing pipeline.

    Args:
        skip_initial_playlist_refresh: Whether to skip the initial playlist refresh
        service_exports_dir: Path to service-specific exports directory
        unorganized_dir: Path to the unorganized directory
        format: Audio format for download
        bitrate: Audio bitrate for download
        cookies_file: Path to cookies file
        pre_skip_existing: Whether to pre-skip existing files
        retries: Number of retry attempts
        apply: Whether to apply changes or just show what would be done
        verbose: Whether to show verbose output
        manual: Whether to use manual mode
        record: Function to record step results
        results: List of step results so far

    Returns:
        None (results are recorded via the record function)
    """
    if skip_initial_playlist_refresh:
        record('download', True, skipped=True)  # Completely skip download step
    else:
        # Normal behavior: proceed if previous step was successful
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
                        cookie_file=cookies_file,
                        pre_skip_existing=pre_skip_existing,
                        retries=retries,
                        validate_only=not apply,  # Dry run mode
                        debug=verbose,
                        manual=manual
                    )
                    record('download', ok)
                except Exception as e:
                    record('download', False, error=str(e))
        else:
            record('download', True, skipped=True)  # Skip if previous step failed


def _import_step(skip_initial_playlist_refresh, unorganized_dir, crate, apply, verbose, record, results):
    """Handle the import step of the unmatched tracks processing pipeline.

    Args:
        skip_initial_playlist_refresh: Whether to skip the initial playlist refresh
        unorganized_dir: Path to the unorganized directory
        crate: Path to the crate/archive directory
        apply: Whether to apply changes or just show what would be done
        verbose: Whether to show verbose output
        record: Function to record step results
        results: List of step results so far

    Returns:
        None (results are recorded via the record function)
    """
    # When skip_initial_playlist_refresh is True, we skip import entirely
    if skip_initial_playlist_refresh:
        record('import', True, skipped=True)  # Completely skip import step
    else:
        # Normal behavior: proceed if download was attempted (not skipped)
        download_attempted = any(r['step'] == 'download' and not r['skipped'] for r in results)
        if download_attempted:
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
        else:
            record('import', True, skipped=True)  # Skip if download failed/skipped


def _sync_playlists_step(service, crate, playlists_path_resolved, exports_dir_opt, apply, verbose,
                        exclude_names, skip_initial_playlist_refresh, results, record):
    """Handle the sync playlists step of the unmatched tracks processing pipeline.

    Args:
        service: Service name ('spotify' or 'soundcloud')
        crate: Path to the crate/archive directory
        playlists_path_resolved: Resolved playlists path
        exports_dir_opt: Optional exports directory override
        apply: Whether to apply changes or just show what would be done
        verbose: Whether to show verbose output
        exclude_names: List of names to exclude from processing
        skip_initial_playlist_refresh: Whether to skip the initial playlist refresh
        results: List of step results so far
        record: Function to record step results

    Returns:
        None (results are recorded via the record function)
    """
    # When skip_initial_playlist_refresh is True, we still perform the sync step
    # but record it as skipped to indicate we didn't do the initial refresh
    # Only perform sync if we had a CSV to work from (step 1 was successful)
    if skip_initial_playlist_refresh:
        # Check if we had a CSV to work from (step 1 was successful)
        had_csv = any(r['step'] == 'refresh-playlists' and r['ok'] for r in results)
        if had_csv:
            print("=== step 4: refresh playlists (reindex only) [SYNC ONLY] ===")
            try:
                # Note: We don't rescrape here as we just want to sync local playlists with current library
                build_playlists(
                    apply=apply,
                    rescrape=False,  # Don't rescrape Spotify - use existing export data
                    reindex=True,    # Rebuild local playlists to match current library
                    names=[],        # No specific names - use scope (owned playlists)
                    exclude_names=[],  # When skipping initial refresh, don't apply exclude names to sync
                    service=service,
                    archive_path=crate,
                    playlists_path=playlists_path_resolved,
                    exports_dir=exports_dir_opt,
                    verbose=verbose
                )
                # Check if this step succeeded by verifying no error was recorded
                # build_playlists doesn't return success/failure, so we assume it worked
                # unless an exception was thrown
                record('refresh-playlists-sync', True, skipped=True)  # Execute but record as skipped
                print("  synced playlists with library")
            except Exception as e:
                record('refresh-playlists-sync', False, error=str(e))
        else:
            # No CSV to work from, skip the sync step entirely
            record('refresh-playlists-sync', True, skipped=True)  # Skip if no CSV to sync from
    else:
        # Normal behavior: proceed if import was successful
        import_success = any(r['step'] == 'import' and r['ok'] and not r['skipped'] for r in results)
        if import_success:
            print("=== step 4: refresh playlists (reindex only) ===")
            try:
                # Note: We don't rescrape here as we just want to sync local playlists with current library
                build_playlists(
                    apply=apply,
                    rescrape=False,  # Don't rescrape Spotify - use existing export data
                    reindex=True,    # Rebuild local playlists to match current library
                    names=[],        # No specific names - use scope (owned playlists)
                    exclude_names=exclude_names or [],
                    service=service,
                    archive_path=crate,
                    playlists_path=playlists_path_resolved,
                    exports_dir=exports_dir_opt,
                    verbose=verbose
                )
                # Check if this step succeeded by verifying no error was recorded
                # build_playlists doesn't return success/failure, so we assume it worked
                # unless an exception was thrown
                record('refresh-playlists-sync', True)
                print("  synced playlists with library")
            except Exception as e:
                record('refresh-playlists-sync', False, error=str(e))
        else:
            record('refresh-playlists-sync', True, skipped=True)  # Skip if import failed/skipped


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
    manual=False,
    verbose=False,
    skip_initial_playlist_refresh=False
):
    """
    Execute the full unmatched tracks processing pipeline.

    Returns:
        dict: {'steps': [{'step', 'ok', 'error', 'skipped'], ...], 'ok': bool}
    """
    # Handle environment variables that serve as defaults for command-line options
    exclude_names, pre_skip_existing, cookies_file, retries = _handle_environment_variables(
        exclude_names, pre_skip_existing, cookies_file, retries)

    # Resolve paths (same as in playlists.build)
    playlists_path_resolved, exports_dir_resolved, service_exports_dir, unorganized_dir, crate = _resolve_paths(
        archive_path_opt, playlists_path_opt, exports_dir_opt, service)

    # Ensure directories exist
    os.makedirs(unorganized_dir, exist_ok=True)

    results = []

    def record(step, ok, error=None, skipped=False):
        results.append({'step': step, 'ok': ok, 'error': error, 'skipped': skipped})

    # Step 1: Refresh playlists to generate unmatched CSV
    _refresh_playlists_step(
        service_exports_dir, skip_initial_playlist_refresh, apply, verbose,
        exclude_names, service, crate, playlists_path_resolved, exports_dir_opt, record
    )
    print()

    # Step 2: Download from unmatched CSV (if it exists and we're not in dry-run or it exists)
    # When skip_initial_playlist_refresh is True, we skip download entirely
    _download_step(
        skip_initial_playlist_refresh, service_exports_dir, unorganized_dir, format, bitrate,
        cookies_file, pre_skip_existing, retries, apply, verbose, manual, record, results
    )
    print()

    # Step 3: Import downloaded files
    # When skip_initial_playlist_refresh is True, we skip import entirely
    _import_step(
        skip_initial_playlist_refresh, unorganized_dir, crate, apply, verbose, record, results
    )
    print()

    # Step 4: Refresh playlists (reindex only) to sync with updated library
    _sync_playlists_step(
        service, crate, playlists_path_resolved, exports_dir_opt, apply, verbose,
        exclude_names, skip_initial_playlist_refresh, results, record
    )
    print()

    # Overall result
    overall_ok = _calculate_overall_result(results)
    print("done." if overall_ok else "completed with errors - see steps above.")
    return {'steps': results, 'ok': overall_ok}


def _calculate_overall_result(results):
    """Calculate the overall result based on step results.

    Args:
        results: List of step result dictionaries

    Returns:
        bool: True if all non-skipped steps were successful, False otherwise
    """
    return all(r['ok'] for r in results if not r['skipped'])
