"""download.spotify_download - download audio from spotify urls via spotdl.

was download_spotify.py. changes from the original beyond the cli.py split:
- organize.library.resolve_library_root() -> lib.paths.archive_path()
- organize.library.build_library_index()/scan_existing_fuzzy() ->
  download.existing (see that module's docstring for why this stayed
  download-package-local instead of moving into lib/)
- organize.library._normalize() -> lib.text.normalize_key()
- the FFMPEG_PATH/ffmpeg_path dual-case getenv -> lib.paths.ffmpeg_path()
  (dual-case fallback dropped project-wide, see REFACTOR_PLAN.md)
- sanitize_filename()/_predict_output_filename()/csv-metadata-reading moved
  out to download.manifest, shared with retry.py (see that module's
  docstring - this was the second near-identical copy of the same csv
  reader, now consolidated).
"""

import os
import sys
import subprocess
import csv
import glob
import time


from lib import config
from lib.paths import archive_path, ffmpeg_path
from lib.text import normalize_key
from download.existing import build_library_index, scan_existing_fuzzy, resolve_output_dir
from download.manifest import predict_output_filename, read_csv_metadata
from download import fallback


def _read_urls_from_source(url_file, verbose):
    """Read URLs from file, directory, or CSV source."""
    urls = []
    try:
        if os.path.isdir(url_file):
            # spotify_manifest.csv is already deduplicated across liked songs + playlists;
            # using it avoids triple-counting urls
            manifest = os.path.join(url_file, "spotify_manifest.csv")
            if os.path.exists(manifest):
                if verbose:
                    print("  using manifest: spotify_manifest.csv")
                urls.extend(_extract_urls_from_csv(manifest))
            else:
                csv_files = glob.glob(os.path.join(url_file, "*.csv"))
                if not csv_files:
                    print(f"no csv files found in directory: {url_file}")
                    return []
                for csv_file in csv_files:
                    if verbose:
                        print(f"  reading urls from: {os.path.basename(csv_file)}")
                    urls.extend(_extract_urls_from_csv(csv_file))
        elif url_file.lower().endswith(".csv"):
            urls = _extract_urls_from_csv(url_file)
        else:
            with open(url_file, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"error reading url source: {e}")
        return []
    return urls


def _deduplicate_urls(urls):
    """Remove duplicate URLs while preserving order."""
    seen = set()
    deduped_urls = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped_urls.append(url)
    return deduped_urls


def _process_manual_mode(urls, metadata, output_dir, format, overwrite_errors, batch_size, cookies_from_browser, verbose):
    """Process URLs in manual mode via fallback."""
    # Process URLs in batches via fallback
    overall_success = True
    num_batches = (len(urls) + batch_size - 1) // batch_size
    if verbose:
        print(f"\nprocessing {len(urls)} urls in {num_batches} batch(es) of up to {batch_size}")
        print(f"output directory: {resolve_output_dir(output_dir)}")

    resolved_output_dir = resolve_output_dir(output_dir)
    resolved_ffmpeg = ffmpeg_path()

    for batch_idx in range(num_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(urls))
        batch = urls[start:end]
        batch_num = batch_idx + 1
        if verbose:
            print(f"\n--- batch {batch_num}/{num_batches} ({len(batch)} urls) ---")

        fallback_succeeded, fallback_failed, batch_succeeded = fallback.process_fallback(
            batch=batch,
            metadata=metadata,
            output_dir=resolved_output_dir,
            format=format,
            overwrite_errors=overwrite_errors,
            cookies_from_browser=cookies_from_browser,
            resolved_ffmpeg=resolved_ffmpeg,
            library_index={},  # manual mode doesn't use library index
            is_spotify=True,
        )

        if not batch_succeeded:
            overall_success = False
            # Log the failed URLs from fallback
            fallback._log_urls("soft_failures.txt", fallback_failed, reason="manual_fallback_failed")
        else:
            print(f"  Batch {batch_num} succeeded via fallback.")

    if overall_success:
        if verbose:
            print(f"\nall batches processed. total: {len(urls)}")
    else:
        print("\ncompleted with some failures. check soft_failures.txt")
    return overall_success


def _check_existing(urls, metadata, output_dir, fmt):
    # returns (existing, new, no_meta, library_root, library_index)
    library_root = output_dir or archive_path()
    print("scanning output folder for existing files...")
    library_index = build_library_index(library_root)
    print(f"found {len(library_index)} audio files on disk.")
    candidates = []
    no_meta = 0
    for url in urls:
        meta = metadata.get(url) or {}
        artist_names, track_name = meta.get("artist", ""), meta.get("track", "")
        if not artist_names or not track_name:
            no_meta += 1
        else:
            candidates.append(predict_output_filename(artist_names, track_name, fmt))
    existing, new = scan_existing_fuzzy(candidates, library_index)
    return existing, new + no_meta, no_meta, library_root, library_index


def _validate_and_prepare_urls(url_file, verbose):
    """Validate URL file and prepare URLs for processing."""
    if not os.path.exists(url_file):
        print(f"error: url file/path not found: {url_file}")
        return None, 0

    urls = _read_urls_from_source(url_file, verbose)
    if not urls:
        return None, 0

    # Deduplicate URLs
    urls = _deduplicate_urls(urls)
    url_count = len(urls)

    if url_count == 0:
        print("no urls found")
        return None, 0

    print(f"url validation complete: {url_count} unique urls.")
    return urls, url_count


def download_spotify(
    url_file,
    output_dir=None,
    format="mp3",
    bitrate="320k",
    overwrite_errors=False,
    skip_existing=False,
    validate_only=False,
    batch_size=1,
    pre_skip_existing=False,
    retries=3,
    retry_delay=3,
    cookies_from_browser=None,
    cookie_file=None,
    debug=False,
    spotdl_fallback=False,
    manual=False,
    verbose=False,
    clean=False,
):
    # Apply environment variable defaults
    pre_skip_existing = (
        config.DOWNLOAD_PRE_SKIP_EXISTING
        if pre_skip_existing is False and config.DOWNLOAD_PRE_SKIP_EXISTING is not None
        else pre_skip_existing
    )
    cookie_file = (
        config.DOWNLOAD_COOKIES_FILE
        if (cookie_file is None or cookie_file == "") and config.DOWNLOAD_COOKIES_FILE
        else cookie_file
    )
    retries = config.DOWNLOAD_RETRIES if retries == 3 and config.DOWNLOAD_RETRIES is not None else retries

    if verbose:
        print(f"processing spotify source: {url_file}")

    # Validate and prepare URLs
    urls, url_count = _validate_and_prepare_urls(url_file, verbose)
    if urls is None:
        return False

    metadata = None
    # We need metadata for fallback (if manual) and for pre-skip existence check
    if manual or pre_skip_existing:
        metadata = _read_metadata_if_needed(url_file, manual, pre_skip_existing)
        if not metadata:
            print("warning: no csVs with track_name/artist_names columns found - skipping existence check and fallback metadata.")
            metadata = {}

    # Pre-skip existence check
    if pre_skip_existing and metadata:
        should_continue, urls, url_count = _handle_pre_skip_existence(urls, metadata, output_dir, format, validate_only, verbose)
        if not should_continue:
            return True  # Either validated only or no URLs left to process
    elif validate_only:
        print("use without --validate-only to download.")
        return True

    # If manual, process via fallback and return
    if manual:
        return _process_manual_mode(
            urls, metadata, output_dir, format, overwrite_errors, batch_size, cookies_from_browser, verbose
        )

    # Otherwise, proceed with spotdl processing (original logic)
    return _process_spotdl_mode(
        urls,
        metadata,
        output_dir,
        format,
        bitrate,
        overwrite_errors,
        skip_existing,
        batch_size,
        retries,
        retry_delay,
        cookies_from_browser,
        cookie_file,
        debug,
        spotdl_fallback,
        verbose,
    )


def _extract_urls_from_csv(csv_path):
    urls = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get("spotify_url")
                if url and url.strip():
                    urls.append(url.strip())
    except Exception as e:
        print(f"warning: failed to read csv {csv_path}: {e}")
    return urls


def _read_metadata_if_needed(url_file, manual, pre_skip_existing):
    """Read metadata if needed for manual mode or pre-skip existence check."""
    if manual or pre_skip_existing:
        return read_csv_metadata(url_file)
    return None


def _handle_pre_skip_existence(urls, metadata, output_dir, format, validate_only, verbose):
    """Handle pre-skip existence check logic."""
    existing, new, no_meta, library_root, library_index = _check_existing(urls, metadata, output_dir, format)
    if verbose:
        print(f"\nexistence check against: {library_root}")
        print(f"  already downloaded : {existing}")
        print(f"  new (to download)  : {new - no_meta}")
        if no_meta:
            print(f"  no metadata        : {no_meta} (will attempt download)")
        print(f"  total unique urls  : {len(urls)}")

    if validate_only:
        print("\nuse without --validate-only to download.")
        return False, [], 0  # Don't continue processing

    new_urls = []
    for url in urls:
        meta = metadata.get(url) or {}
        a, t = meta.get("artist", ""), meta.get("track", "")
        if not a or not t:
            new_urls.append(url)
        else:
            predicted = predict_output_filename(a, t, format)
            stem = os.path.splitext(predicted)[0]
            if normalize_key(stem) not in library_index:
                new_urls.append(url)
    skipped = len(urls) - len(new_urls)
    if verbose:
        print(f"\npre-skip: skipping {skipped} existing files, {len(new_urls)} to download.")

    return True, new_urls, len(new_urls)  # Continue processing with new URLs


def _build_spotdl_command(
    batch, format, bitrate, output_dir, overwrite_errors, skip_existing, cookie_file, cookies_from_browser, debug
):
    """Build the spotdl command with all necessary options."""
    cmd = [sys.executable, "-m", "spotdl", "download"] + batch
    cmd.extend(["--format", format, "--bitrate", bitrate])
    cmd.extend(["--output", os.path.join(output_dir, "{artists} - {title}.{output-ext}")])

    if overwrite_errors:
        cmd.append("--overwrite")
    if skip_existing:
        cmd.append("--skip-existing")
    if cookie_file:
        cmd.extend(["--cookie-file", cookie_file])
    elif cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    yt_dlp_extra_args = (
        '--user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/127.0 Safari/537.36" '
        '--referer "https://music.youtube.com/"'
    )
    cmd.append("--lyrics")
    log_level = "DEBUG" if debug else "INFO"
    cmd.extend(["--log-level", log_level, "--print-errors", "--yt-dlp-args", yt_dlp_extra_args])
    resolved_ffmpeg = ffmpeg_path()
    if resolved_ffmpeg:
        cmd.extend(["--ffmpeg", resolved_ffmpeg])
    return cmd


def _execute_spotdl_batch(cmd, batch, batch_num, retries, retry_delay, verbose, hard_failure_patterns, soft_failure_patterns):
    """Execute a single batch of URLs with spotdl and handle retries."""
    attempt = 0
    batch_succeeded = False
    hard_failure_detected = False
    while attempt <= retries and not batch_succeeded:
        returncode, combined_output = _run_spotdl_process(cmd)

        if returncode is None:  # Error occurred running spotdl
            break  # exit while loop to go to fallback

        if _is_hard_failure(combined_output, hard_failure_patterns, verbose, batch):
            hard_failure_detected = True
            break  # exit while loop to go to fallback

        if returncode != 0 or _is_soft_failure(combined_output, soft_failure_patterns, verbose, batch, attempt, retries):
            attempt += 1
            if attempt <= retries:
                if verbose:
                    print(f"exit code {returncode}, retrying ({attempt}/{retries})...")
                time.sleep(retry_delay)
                continue
            else:
                if verbose:
                    print(f"batch failed after {retries} retries")
                break  # exit while loop to go to fallback
        else:
            # Success: returncode == 0 and not a soft failure
            if verbose:
                print(f"batch {batch_num} downloaded successfully")
            batch_succeeded = True
            break  # exit while loop

    return batch_succeeded, hard_failure_detected


def _is_hard_failure(combined_output, hard_failure_patterns, verbose, batch):
    """Check if output indicates a hard failure."""
    if any(p in combined_output for p in hard_failure_patterns):
        if verbose:
            print(f"hard failure (track unavailable): {batch}")
        return True
    return False


def _is_soft_failure(combined_output, soft_failure_patterns, verbose, batch, max_retries, current_attempt):
    """Check if output indicates a soft failure and handle retry logic."""
    if any(p in combined_output for p in soft_failure_patterns):
        if current_attempt < max_retries:
            if verbose:
                print(f"soft failure detected, retrying ({current_attempt + 1}/{max_retries})...")
            return False  # Continue retrying
        else:
            reason = next((p for p in soft_failure_patterns if p in combined_output), "soft_failure")
            if verbose:
                print(f"soft failure after {max_retries} retries ({reason}): {batch}")
            return True  # Stop retrying, proceed to fallback
    return False  # Not a soft failure


def _run_spotdl_process(cmd):
    """Run spotdl process and return returncode and combined output."""
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace"
        )
        captured_lines = []
        for line in proc.stdout:
            print(line, end="", flush=True)
            captured_lines.append(line)
        proc.wait()
        returncode = proc.returncode
        combined_output = "".join(captured_lines)
        return returncode, combined_output
    except Exception as e:
        print(f"error running spotdl: {e}")
        return None, None  # Indicate error occurred


def _process_spotdl_mode(
    urls,
    metadata,
    output_dir,
    format,
    bitrate,
    overwrite_errors,
    skip_existing,
    batch_size,
    retries,
    retry_delay,
    cookies_from_browser,
    cookie_file,
    debug,
    spotdl_fallback,
    verbose,
):
    """Process URLs using spotdl (original logic)."""
    # spotdl exits 0 even when nothing downloads - scan output for these markers
    SOFT_FAILURE_PATTERNS = [
        "AudioProviderError",
        "LookupError",
        "PermissionError",
        "No results found",
        "YT-DLP download error",
        "returned no usable results",
    ]
    # track is genuinely gone, no point retrying
    HARD_FAILURE_PATTERNS = [
        "Track no longer exists",
        "SongError",
    ]

    # resolve once so it matches whatever the pre-skip existence check used
    resolved_output_dir, resolved_ffmpeg = _resolve_paths_and_ffmpeg(output_dir)

    overall_success = True
    num_batches = (len(urls) + batch_size - 1) // batch_size
    if verbose:
        print(f"\nprocessing {len(urls)} urls in {num_batches} batch(es) of up to {batch_size}")
        print(f"output directory: {resolved_output_dir}")

    for batch_idx in range(num_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(urls))
        batch = urls[start:end]
        batch_num = batch_idx + 1
        if verbose:
            print(f"\n--- batch {batch_num}/{num_batches} ({len(batch)} urls) ---")

        cmd = _build_spotdl_command(
            batch=batch,
            format=format,
            bitrate=bitrate,
            output_dir=resolved_output_dir,
            overwrite_errors=overwrite_errors,
            skip_existing=skip_existing,
            cookie_file=cookie_file,
            cookies_from_browser=cookies_from_browser,
            debug=debug,
        )

        print(f"running spotdl for: {batch}")

        batch_succeeded, hard_failure_detected = _execute_spotdl_batch(
            cmd=cmd,
            batch=batch,
            batch_num=batch_num,
            retries=retries,
            retry_delay=retry_delay,
            verbose=verbose,
            hard_failure_patterns=HARD_FAILURE_PATTERNS,
            soft_failure_patterns=SOFT_FAILURE_PATTERNS,
        )

        overall_success = _handle_batch_result(
            hard_failure_detected=hard_failure_detected,
            batch_succeeded=batch_succeeded,
            spotdl_fallback=spotdl_fallback,
            verbose=verbose,
            batch=batch,
            batch_num=batch_num,
            overall_success=overall_success,
            metadata=metadata,
            resolved_output_dir=resolved_output_dir,
            format=format,
            overwrite_errors=overwrite_errors,
            cookies_from_browser=cookies_from_browser,
            resolved_ffmpeg=resolved_ffmpeg,
            fallback=fallback,
        )

    if overall_success:
        if verbose:
            print(f"\nall batches processed. total: {len(urls)}")
    else:
        if verbose:
            print("\ncompleted with some failures. check failed_downloads.txt and soft_failures.txt")
    return overall_success


def _resolve_paths_and_ffmpeg(output_dir):
    """Resolve output directory and ffmpeg path."""
    resolved_output_dir = resolve_output_dir(output_dir)
    resolved_ffmpeg = ffmpeg_path()
    return resolved_output_dir, resolved_ffmpeg


def _handle_batch_result(
    hard_failure_detected,
    batch_succeeded,
    spotdl_fallback,
    verbose,
    batch,
    batch_num,
    overall_success,
    metadata,
    resolved_output_dir,
    format,
    overwrite_errors,
    cookies_from_browser,
    resolved_ffmpeg,
    fallback,
):
    """Handle the result of a batch processing attempt."""
    # Handle hard failures specially - log to failed_downloads.txt and skip fallback
    if hard_failure_detected:
        if verbose:
            print(f"  Batch {batch_num} had hard failure (track unavailable).")
        overall_success = False
        # Log the failed URLs to failed_downloads.txt with track_unavailable reason
        fallback._log_urls("failed_downloads.txt", batch, reason="track_unavailable")
    elif not batch_succeeded and spotdl_fallback:
        # Process fallback using the fallback module
        fallback_succeeded, fallback_failed, batch_succeeded = fallback.process_fallback(
            batch=batch,
            metadata=metadata,
            output_dir=resolved_output_dir,
            format=format,
            overwrite_errors=overwrite_errors,
            cookies_from_browser=cookies_from_browser,
            resolved_ffmpeg=resolved_ffmpeg,
            library_index={},  # Note: using empty library_index for consistency with manual mode?
            is_spotify=True,
        )
        # Update overall_success based on fallback results
        if not batch_succeeded:
            overall_success = False
            # Log the failed URLs from fallback
            fallback._log_urls("soft_failures.txt", fallback_failed, reason="spotdl_fallback_failed")
    elif not batch_succeeded:
        # No fallback or fallback not enabled, log failure
        if verbose:
            print(f"  Batch {batch_num} failed after all retries.")
        overall_success = False
        # Determine if it was hard or soft failure? We don't have reason here.
        # For simplicity, log to soft_failures.txt (could be either)
        fallback._log_urls("soft_failures.txt", batch, reason="spotdl_exhausted_retries")

    return overall_success
