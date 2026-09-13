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

from lib.paths import archive_path, ffmpeg_path
from lib.text import normalize_key
from download.existing import build_library_index, scan_existing_fuzzy, resolve_output_dir
from download.manifest import predict_output_filename, read_csv_metadata


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
        artist_names, track_name = meta.get('artist', ''), meta.get('track', '')
        if not artist_names or not track_name:
            no_meta += 1
        else:
            candidates.append(predict_output_filename(artist_names, track_name, fmt))
    existing, new = scan_existing_fuzzy(candidates, library_index)
    return existing, new + no_meta, no_meta, library_root, library_index


def download_spotify(url_file, output_dir=None, format='mp3', bitrate='320k',
                   overwrite_errors=False, skip_existing=False,
                   validate_only=False, batch_size=1, pre_skip_existing=False,
                   retries=3, retry_delay=3, cookies_from_browser=None, cookie_file=None,
                   debug=False):
    print(f"processing spotify source: {url_file}")

    if not os.path.exists(url_file):
        print(f"error: url file/path not found: {url_file}")
        return False

    urls = []
    try:
        if os.path.isdir(url_file):
            # spotify_manifest.csv is already deduplicated across liked songs + playlists;
            # using it avoids triple-counting urls
            manifest = os.path.join(url_file, 'spotify_manifest.csv')
            if os.path.exists(manifest):
                print(f"  using manifest: spotify_manifest.csv")
                urls.extend(_extract_urls_from_csv(manifest))
            else:
                csv_files = glob.glob(os.path.join(url_file, '*.csv'))
                if not csv_files:
                    print(f"no csv files found in directory: {url_file}")
                    return False
                for csv_file in csv_files:
                    print(f"  reading urls from: {os.path.basename(csv_file)}")
                    urls.extend(_extract_urls_from_csv(csv_file))
        elif url_file.lower().endswith('.csv'):
            urls = _extract_urls_from_csv(url_file)
        else:
            with open(url_file, 'r', encoding='utf-8') as f:
                urls = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"error reading url source: {e}")
        return False

    seen = set()
    deduped_urls = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped_urls.append(url)
    urls = deduped_urls
    url_count = len(urls)

    if url_count == 0:
        print("no urls found")
        return False

    print(f"url validation complete: {url_count} unique urls.")

    if pre_skip_existing:
        metadata = read_csv_metadata(url_file)
        if not metadata:
            print("warning: no csvs with track_name/artist_names columns found - skipping existence check.")
        else:
            existing, new, no_meta, library_root, library_index = _check_existing(urls, metadata, output_dir, format)
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
                a, t = meta.get('artist', ''), meta.get('track', '')
                if not a or not t:
                    new_urls.append(url)
                else:
                    predicted = predict_output_filename(a, t, format)
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

    # spotdl exits 0 even when nothing downloads - scan output for these markers
    SOFT_FAILURE_PATTERNS = [
        'AudioProviderError',
        'LookupError',
        'PermissionError',
        'No results found',
        'YT-DLP download error',
        'returned no usable results',
    ]
    # track is genuinely gone, no point retrying
    HARD_FAILURE_PATTERNS = [
        'Track no longer exists',
        'SongError',
    ]

    # resolve once so it matches whatever the pre-skip existence check used
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

        cmd = [sys.executable, "-m", "spotdl", "download"] + batch
        cmd.extend(["--format", format, "--bitrate", bitrate])
        cmd.extend(["--output", os.path.join(resolved_output_dir, "{artists} - {title}.{output-ext}")])

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
        cmd.extend(["--log-level",log_level,"--print-errors","--yt-dlp-args",yt_dlp_extra_args])
        resolved_ffmpeg = ffmpeg_path()
        if resolved_ffmpeg:
            cmd.extend(["--ffmpeg", resolved_ffmpeg])

        print(f"running spotdl for: {batch}")

        attempt = 0
        while attempt <= retries:
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace'
                )
                captured_lines = []
                for line in proc.stdout:
                    print(line, end='', flush=True)
                    captured_lines.append(line)
                proc.wait()
                returncode = proc.returncode
                combined_output = ''.join(captured_lines)
            except Exception as e:
                print(f"error running spotdl: {e}")
                overall_success = False
                _log_urls('failed_downloads.txt', batch)
                break

            if any(p in combined_output for p in HARD_FAILURE_PATTERNS):
                print(f"hard failure (track unavailable): {batch}")
                _log_urls('failed_downloads.txt', batch, reason='track_unavailable')
                break

            if returncode != 0:
                attempt += 1
                if attempt <= retries:
                    print(f"exit code {returncode}, retrying ({attempt}/{retries})...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"batch failed after {retries} retries")
                    overall_success = False
                    _log_urls('failed_downloads.txt', batch, reason='download_failed')
                    break

            if any(p in combined_output for p in SOFT_FAILURE_PATTERNS):
                attempt += 1
                if attempt <= retries:
                    print(f"soft failure detected, retrying ({attempt}/{retries})...")
                    time.sleep(retry_delay)
                    continue
                else:
                    reason = next((p for p in SOFT_FAILURE_PATTERNS if p in combined_output), 'soft_failure')
                    print(f"soft failure after {retries} retries ({reason}): {batch}")
                    _log_urls('soft_failures.txt', batch, reason=reason)
                break

            print(f"batch {batch_num} downloaded successfully")
            break

    if overall_success:
        print(f"\nall batches processed. total: {url_count}")
    else:
        print(f"\ncompleted with some failures. check failed_downloads.txt and soft_failures.txt")
    return overall_success


def _log_urls(filename, urls, reason=None):
    with open(filename, 'a', encoding='utf-8') as f:
        for url in urls:
            line = f"{url}  # {reason}" if reason else url
            f.write(line + '\n')


def _extract_urls_from_csv(csv_path):
    urls = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get('spotify_url')
                if url and url.strip():
                    urls.append(url.strip())
    except Exception as e:
        print(f"warning: failed to read csv {csv_path}: {e}")
    return urls
