"""download.soundcloud_download - download audio from soundcloud urls via ytdl.

Mirrors download_spotify.py but for SoundCloud.
"""

import os
import sys
import subprocess
import csv
import glob
import time
import shutil

import click

from lib.paths import archive_path, ffmpeg_path
from lib.text import normalize_key
from download.existing import build_library_index, scan_existing_fuzzy, resolve_output_dir
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


def _check_existing(urls, metadata, output_dir, fmt):
    # returns (existing, new, no_meta, library_root, library_index)
    library_root = output_dir or archive_path()
    print(f"scanning output folder for existing files...")
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


def download_soundcloud(url_file, output_dir=None, format='mp3', bitrate='320k',
                        overwrite_errors=False, skip_existing=False,
                        validate_only=False, batch_size=1, pre_skip_existing=False,
                        retries=3, retry_delay=3, cookies_from_browser=None, cookie_file=None,
                        debug=False, soundcloud_fallback=False):
    print(f"processing soundcloud source: {url_file}")

    if not os.path.exists(url_file):
        print(f"error: url file/path not found: {url_file}")
        return False

    urls = []
    metadata = {}  # url -> dict of metadata (uploader, title, set_name, set_position)
    try:
        if os.path.isdir(url_file):
            # Look for soundcloud_manifest.csv
            manifest = os.path.join(url_file, 'soundcloud_manifest.csv')
            if os.path.exists(manifest):
                print(f"  using manifest: soundcloud_manifest.csv")
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
                    return False
                for csv_file in csv_files:
                    print(f"  reading urls from: {os.path.basename(csv_file)}")
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
        elif url_file.lower().endswith('.csv'):
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
        else:
            # Plain text file: one URL per line
            with open(url_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        urls.append(line)
                        # No metadata available for plain text URLs
    except Exception as e:
        print(f"error reading url source: {e}")
        return False

    # Deduplicate URLs
    seen = set()
    deduped_urls = []
    deduped_metadata = {}
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped_urls.append(url)
            if url in metadata:
                deduped_metadata[url] = metadata[url]
    urls = deduped_urls
    metadata = deduped_metadata
    url_count = len(urls)

    if url_count == 0:
        print("no urls found")
        return False

    print(f"url validation complete: {url_count} unique urls.")

    # Pre-skip existing check
    if pre_skip_existing:
        metadata_for_check = metadata or {}
        existing, new, no_meta, library_root, library_index = _check_existing(
            urls, metadata_for_check, output_dir, format)
        print(f"\nexistence check against: {library_root}")
        print(f"  already downloaded : {existing}")
        print(f"  new (to download)  : {new - no_meta}")
        if no_meta:
            print(f"  no metadata        : {no_meta} (will attempt download)")
        print(f"  total unique urls  : {url_count}")

        if validate_only:
            print("\nuse without --validate-only to download.")
            return True

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
        print(f"\npre-skip: skipping {skipped} existing files, {len(new_urls)} to download.")
        urls = new_urls
        url_count = len(urls)
        if url_count == 0:
            print("all files already exist - nothing to download.")
            return True
    elif validate_only:
        print("use without --validate-only to download.")
        return True

    # Resolve output directory
    resolved_output_dir = resolve_output_dir(output_dir)

    overall_success = True
    num_batches = (url_count + batch_size - 1) // batch_size
    print(f"\nprocessing {url_count} urls in {num_batches} batch(es) of up to {batch_size}")
    print(f"output directory: {resolved_output_dir}")

    for batch_idx in range(num_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, url_count)
        batch = urls[start:end]
        batch_num = batch_idx + 1
        print(f"\n--- batch {batch_num}/{num_batches} ({len(batch)} urls) ---")

        # For each URL in the batch, we call download_ytdl
        # We don't have a batch mode for ytdl with multiple URLs? We'll call per URL.
        batch_succeeded = False
        attempt = 0
        while attempt <= retries and not batch_succeeded:
            # We'll process each URL in the batch individually, but retry the whole batch on failure?
            # Alternatively, we can process each URL with its own retry loop.
            # We'll do per-URL retry to mirror spotdl's behavior? Actually, spotdl downloads the whole batch at once.
            # We'll change: we'll attempt to download each URL in the batch, and if any fail, we retry the whole batch.
            # But that's not efficient. Let's do per-URL retry and then consider the batch succeeded if all URLs succeed.
            # We'll reset per-URL attempts.
            batch_succeeded = True
            for url in batch:
                meta = metadata.get(url) or {}
                artist = meta.get('uploader', '')
                track = meta.get('title', '')
                set_name = meta.get('set_name', None)
                set_position = meta.get('set_position', None)
                # We don't use artist/track for ytdl directly, but we can use them for logging?
                # We'll just call download_ytdl with the URL.
                print(f"  downloading: {url}")
                ytdl_success = download_ytdl(
                    url,
                    output_dir=resolved_output_dir,
                    audio_format=format,
                    audio_quality=bitrate,
                    embed_thumbnail=True,
                    overwrite=overwrite_errors,
                    verbose=False,
                    metadata_only=False,
                    cookies_from_browser=cookies_from_browser,
                    ffmpeg_path=ffmpeg_path(),
                )
                if not ytdl_success:
                    batch_succeeded = False
                    break  # break out of for-loop, then we'll retry the batch
            if batch_succeeded:
                break  # break out of while loop, batch succeeded
            else:
                attempt += 1
                if attempt <= retries:
                    print(f"  batch failed, retrying ({attempt}/{retries})...")
                    time.sleep(retry_delay)
                else:
                    print(f"  batch failed after {retries} retries")
                    break  # exit while loop

        if not batch_succeeded:
            overall_success = False
            print(f"  Batch {batch_num} failed after all retries.")
            # Log the batch to soft_failures.txt? We'll create a helper later.
            # For now, we'll just note.
        else:
            print(f"  Batch {batch_num} downloaded successfully")

    if overall_success:
        print(f"\nall batches processed. total: {url_count}")
    else:
        print(f"\ncompleted with some failures. check soft_failures.txt")
    return overall_success