"""download.soundcloud_download - download audio from soundcloud urls via ytdl.

Mirrors download_spotify.py but for SoundCloud.
"""

import os
import csv
import glob
import time


from lib.paths import archive_path, ffmpeg_path
from lib.text import normalize_key
from download.existing import build_library_index, scan_existing_fuzzy, resolve_output_dir
from download import fallback
from download.ytdl import download_ytdl


def _predict_soundcloud_filename(artist, track, set_name=None, set_position=None, fmt='mp3'):
    """Predict the filename that ytdl will output for a SoundCloud track.
    If set_name and set_position are provided, use the playlist template:
        '%(playlist)s/%(playlist_index)02d - %(uploader)s - %(title)s.%(ext)s'
    Otherwise, use the single template:
        '%(uploader)s - %(title)s.%(ext)s'
    """
    if set_name and set_position is not None:
        # Playlist template: set_name is playlist, set_position is playlist_index
        # Note: ytdl uses zero-padded two-digit index for playlist_index
        predicted = f"{set_name}/{set_position:02d} - {artist} - {track}.{fmt}"
    else:
        # Single template
        predicted = f"{artist} - {track}.{fmt}"
    return predicted


def _deduplicate_urls_and_metadata(urls, metadata):
    """Remove duplicate URLs while preserving order and associated metadata."""
    seen = set()
    deduped_urls = []
    deduped_metadata = {}
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped_urls.append(url)
            if url in metadata:
                deduped_metadata[url] = metadata[url]
    return deduped_urls, deduped_metadata


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
        artist_names = meta.get('uploader', '')
        track_name = meta.get('title', '')
        set_name = meta.get('set_name', None)
        set_position = meta.get('set_position', None)
        if not artist_names or not track_name:
            no_meta += 1
        else:
            predicted = _predict_soundcloud_filename(artist_names, track_name, set_name, set_position, fmt)
            candidates.append(predicted)
    existing, new = scan_existing_fuzzy(candidates, library_index)
    return existing, new + no_meta, no_meta, library_root, library_index


def _handle_pre_skip_existence(urls, metadata, output_dir, format, validate_only, verbose):
    """Handle pre-skip existence check logic."""
    metadata_for_check = metadata or {}
    existing, new, no_meta, library_root, library_index = _check_existing(
        urls, metadata_for_check, output_dir, format)
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
        artist, track = meta.get('uploader', ''), meta.get('title', '')
        set_name = meta.get('set_name', None)
        set_position = meta.get('set_position', None)
        if not artist or not track:
            new_urls.append(url)
        else:
            predicted = _predict_soundcloud_filename(artist, track, set_name, set_position, format)
            stem = os.path.splitext(predicted)[0]
            if normalize_key(stem) not in library_index:
                new_urls.append(url)
    skipped = len(urls) - len(new_urls)
    if verbose:
        print(f"\npre-skip: skipping {skipped} existing files, {len(new_urls)} to download.")

    return True, new_urls, len(new_urls)  # Continue processing with new URLs


def _read_urls_and_metadata(url_file, verbose):
    """Read URLs and metadata from file, directory, or CSV source."""
    if os.path.isdir(url_file):
        return _read_from_directory(url_file, verbose)
    elif url_file.lower().endswith('.csv'):
        return _read_from_csv_file(url_file, verbose)
    else:
        return _read_from_plain_text_file(url_file, verbose)


def _read_from_directory(url_file, verbose):
    """Read URLs and metadata from a directory."""
    urls = []
    metadata = {}  # url -> dict of metadata (uploader, title, set_name, set_position)
    try:
        # Look for soundcloud_manifest.csv
        manifest = os.path.join(url_file, 'soundcloud_manifest.csv')
        if os.path.exists(manifest):
            if verbose:
                print("  using manifest: soundcloud_manifest.csv")
            with open(manifest, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    url = row.get('spotify_url') or row.get('track_url')
                    if url and url.strip():
                        urls.append(url.strip())
                        metadata[url.strip()] = {
                            'uploader': row.get('uploader') or row.get('artist_names', ''),
                            'title': row.get('title') or row.get('track_name', ''),
                            'set_name': row.get('set_name', None),
                            'set_position': row.get('set_position', None),
                        }
        else:
            csv_files = glob.glob(os.path.join(url_file, '*.csv'))
            if not csv_files:
                print(f"no csv files found in directory: {url_file}")
                return None, None
            for csv_file in csv_files:
                if verbose:
                    print(f"  reading urls from: {os.path.basename(csv_file)}")
                _read_csv_file_and_populate(csv_file, urls, metadata, verbose)
        return urls, metadata
    except Exception as e:
        print(f"error reading url source: {e}")
        return None, None


def _read_from_csv_file(url_file, verbose):
    """Read URLs and metadata from a single CSV file."""
    urls = []
    metadata = {}  # url -> dict of metadata (uploader, title, set_name, set_position)
    try:
        # Read CSV for metadata and URLs
        with open(url_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get('spotify_url') or row.get('track_url')
                if url and url.strip():
                    urls.append(url.strip())
                    metadata[url.strip()] = {
                        'uploader': row.get('uploader') or row.get('artist_names', ''),
                        'title': row.get('title') or row.get('track_name', ''),
                        'set_name': row.get('set_name', None),
                        'set_position': row.get('set_position', None),
                    }
        return urls, metadata
    except Exception as e:
        print(f"error reading url source: {e}")
        return None, None


def _read_from_plain_text_file(url_file, verbose):
    """Read URLs from a plain text file (one URL per line)."""
    urls = []
    try:
        # Plain text file: one URL per line
        with open(url_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    urls.append(line)
                    # No metadata available for plain text URLs
        metadata = {}  # No metadata for plain text
        return urls, metadata
    except Exception as e:
        print(f"error reading url source: {e}")
        return None, None


def _read_csv_file_and_populate(csv_file, urls, metadata, verbose):
    """Read a CSV file and populate urls and metadata dictionaries."""
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get('spotify_url') or row.get('track_url')
            if url and url.strip():
                urls.append(url.strip())
                metadata[url.strip()] = {
                    'uploader': row.get('uploader') or row.get('artist_names', ''),
                    'title': row.get('title') or row.get('track_name', ''),
                    'set_name': row.get('set_name', None),
                    'set_position': row.get('set_position', None),
                }


def _process_manual_mode(urls, metadata, output_dir, format,
                        overwrite_errors, batch_size, cookies_from_browser, verbose):
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
            is_spotify=False
        )

        if not batch_succeeded:
            overall_success = False
            # Log the failed URLs from fallback
            fallback._log_urls('soft_failures.txt', fallback_failed, reason='manual_fallback_failed')
        else:
            if verbose:
                print(f"  Batch {batch_num} succeeded via fallback.")

    if overall_success:
        print(f"\nall batches processed. total: {len(urls)}")
    else:
        print("\ncompleted with some failures. check soft_failures.txt")
    return overall_success


def _download_url_with_retry(url, output_dir, format, bitrate, overwrite_errors,
                           verbose, cookies_from_browser, max_retries, retry_delay):
    """Download a single URL with retry logic."""
    for attempt in range(max_retries + 1):
        if verbose:
            print(f"  downloading: {url}")
        ytdl_success = download_ytdl(
            url,
            output_dir=output_dir,
            audio_format=format,
            audio_quality=bitrate,
            embed_thumbnail=True,
            overwrite=overwrite_errors,
            verbose=verbose,
            metadata_only=False,
            cookies_from_browser=cookies_from_browser,
            ffmpeg_path=ffmpeg_path(),
        )
        if ytdl_success:
            return True
        if attempt < max_retries:
            if verbose:
                print(f"  failed, retrying ({attempt + 1}/{max_retries})...")
            time.sleep(retry_delay)
    if verbose:
        print(f"  failed after {max_retries} retries")
    return False


def _process_ytdl_batch(batch, output_dir, format, bitrate, overwrite_errors,
                       verbose, cookies_from_browser, retries, retry_delay):
    """Process a single batch of URLs with ytdl."""
    batch_succeeded = True
    for url in batch:
        if not _download_url_with_retry(
            url, output_dir, format, bitrate, overwrite_errors,
            verbose, cookies_from_browser, retries, retry_delay
        ):
            batch_succeeded = False
            # Continue processing other URLs in batch but mark batch as failed
    return batch_succeeded


def _process_ytdl_mode(urls, metadata, output_dir, format, bitrate,
                       overwrite_errors, skip_existing, batch_size,
                       retries, retry_delay, cookies_from_browser, verbose):
    """Process URLs using ytdl (original logic)."""
    # Resolve output directory
    resolved_output_dir = resolve_output_dir(output_dir)

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

        # Process the batch
        batch_succeeded = _process_ytdl_batch(
            batch, resolved_output_dir, format, bitrate, overwrite_errors,
            verbose, cookies_from_browser, retries, retry_delay
        )

        if not batch_succeeded:
            overall_success = False
            if verbose:
                print(f"  Batch {batch_num} had failures.")
            # Log the batch to soft_failures.txt
            fallback._log_urls('soft_failures.txt', batch, reason='ytdl_exhausted_retries')
        else:
            if verbose:
                print(f"  Batch {batch_num} downloaded successfully")

    if overall_success:
        if verbose:
            print(f"\nall batches processed. total: {len(urls)}")
    else:
        if verbose:
            print("\ncompleted with some failures. check soft_failures.txt")
    return overall_success


def download_soundcloud(url_file, output_dir=None, format='mp3', bitrate='320k',
                        overwrite_errors=False, skip_existing=False,
                        validate_only=False, batch_size=1, pre_skip_existing=False,
                        retries=3, retry_delay=3, cookies_from_browser=None, cookie_file=None,
                        debug=False, soundcloud_fallback=False, manual=False, verbose=False):
    if verbose:
        print(f"processing soundcloud source: {url_file}")

    if not os.path.exists(url_file):
        print(f"error: url file/path not found: {url_file}")
        return False

    # Read URLs and metadata
    urls, metadata = _read_urls_and_metadata(url_file, verbose)
    if urls is None:
        return False

    # Deduplicate URLs
    urls, metadata = _deduplicate_urls_and_metadata(urls, metadata)
    url_count = len(urls)

    if url_count == 0:
        print("no urls found")
        return False

    print(f"url validation complete: {url_count} unique urls.")

    # Pre-skip existing check
    if pre_skip_existing:
        should_continue, urls, url_count = _handle_pre_skip_existence(
            urls, metadata, output_dir, format, validate_only, verbose
        )
        if not should_continue:
            return True  # Either validated only or no URLs left to process
    elif validate_only:
        print("use without --validate-only to download.")
        return True

    # If manual, process via fallback and return
    if manual:
        return _process_manual_mode(urls, metadata, output_dir, format,
                                  overwrite_errors, batch_size, cookies_from_browser, verbose)

    # Otherwise, proceed with ytdl processing (original logic)
    return _process_ytdl_mode(urls, metadata, output_dir, format, bitrate,
                            overwrite_errors, skip_existing, batch_size,
                            retries, retry_delay, cookies_from_browser, verbose)
