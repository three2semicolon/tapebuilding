import argparse
import os
import sys
import subprocess
import csv
import glob
import re
import time

from .spotify_utils import get_export_dir
from organize.library import resolve_library_root, build_library_index, scan_existing_fuzzy


def sanitize_filename(filename):
    # must match spotdl's sanitization so predicted filenames == what spotdl writes
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    filename = filename.strip('. ')
    return filename


def _resolve_output_dir(output_dir, create=True):
    final = output_dir or resolve_library_root()
    if create:
        os.makedirs(final, exist_ok=True)
    return final


def _predict_output_filename(artist_names, track_name, fmt):
    return sanitize_filename(f"{artist_names} - {track_name}.{fmt}")


def _read_csv_metadata_from_file(csv_path):
    metadata = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            sample = f.read(1024)
            f.seek(0)
            delimiter = csv.Sniffer().sniff(sample).delimiter
            reader = csv.DictReader(f, delimiter=delimiter)
            if reader.fieldnames:
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
            if not {'track_name', 'artist_names'}.issubset(set(reader.fieldnames or [])):
                return {}
            for row in reader:
                url = (row.get('spotify_url') or '').strip()
                if url and url not in metadata:
                    metadata[url] = (
                        (row.get('artist_names') or '').strip(),
                        (row.get('track_name') or '').strip(),
                    )
    except Exception as e:
        print(f"warning: failed to read csv metadata from {csv_path}: {e}")
    return metadata


def _read_csv_metadata(url_file):
    if os.path.isdir(url_file):
        merged = {}
        for csv_path in glob.glob(os.path.join(url_file, '*.csv')):
            meta = _read_csv_metadata_from_file(csv_path)
            # first-seen wins for dedup consistency
            for url, val in meta.items():
                if url not in merged:
                    merged[url] = val
        return merged if merged else None
    elif url_file.lower().endswith('.csv'):
        result = _read_csv_metadata_from_file(url_file)
        return result if result else None
    return None


def _check_existing(urls, metadata, output_dir, fmt):
    # returns (existing, new, no_meta, library_root, library_index)
    library_root = output_dir or resolve_library_root()
    print(f"scanning output folder for existing files...")
    library_index = build_library_index(library_root)
    print(f"found {len(library_index)} audio files on disk.")
    candidates = []
    no_meta = 0
    for url in urls:
        artist_names, track_name = metadata.get(url, ('', ''))
        if not artist_names or not track_name:
            no_meta += 1
        else:
            candidates.append(_predict_output_filename(artist_names, track_name, fmt))
    existing, new = scan_existing_fuzzy(candidates, library_index)
    return existing, new + no_meta, no_meta, library_root, library_index


def download_music(url_file, output_dir=None, format='mp3', bitrate='320k',
                   overwrite_errors=False, skip_existing=False, verbose=False,
                   validate_only=False, batch_size=1, pre_skip_existing=False):
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
        metadata = _read_csv_metadata(url_file)
        if metadata is None:
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
                a, t = metadata.get(url, ('', ''))
                if not a or not t:
                    new_urls.append(url)
                else:
                    predicted = _predict_output_filename(a, t, format)
                    stem = os.path.splitext(predicted)[0]
                    from organize.library import _normalize
                    if _normalize(stem) not in library_index:
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
    MAX_RETRIES = 0
    RETRY_DELAY = 3

    overall_success = True
    num_batches = (url_count + batch_size - 1) // batch_size
    print(f"\nprocessing {url_count} urls in {num_batches} batch(es) of up to {batch_size}")

    for batch_idx in range(num_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, url_count)
        batch = urls[start:end]
        batch_num = batch_idx + 1
        print(f"\n--- batch {batch_num}/{num_batches} ({len(batch)} urls) ---")

        cmd = [sys.executable, "-m", "spotdl", "download"] + batch
        cmd.extend(["--format", format, "--bitrate", bitrate])

        if overwrite_errors:
            cmd.append("--overwrite")
        if skip_existing:
            cmd.append("--skip-existing")
        if verbose:
            cmd.append("--verbose")

        cmd.extend(["--output", _resolve_output_dir(output_dir)])

        ffmpeg_path = os.getenv('FFMPEG_PATH') or os.getenv('ffmpeg_path')
        if ffmpeg_path:
            cmd.extend(["--ffmpeg", ffmpeg_path])

        if not verbose:
            print(f"running spotdl for: {batch}")

        attempt = 0
        while attempt <= MAX_RETRIES:
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
                if attempt <= MAX_RETRIES:
                    print(f"exit code {returncode}, retrying ({attempt}/{MAX_RETRIES})...")
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    print(f"batch failed after {MAX_RETRIES} retries")
                    overall_success = False
                    _log_urls('failed_downloads.txt', batch, reason='download_failed')
                    break

            if any(p in combined_output for p in SOFT_FAILURE_PATTERNS):
                attempt += 1
                if attempt <= MAX_RETRIES:
                    print(f"soft failure detected, retrying ({attempt}/{MAX_RETRIES})...")
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    reason = next((p for p in SOFT_FAILURE_PATTERNS if p in combined_output), 'soft_failure')
                    print(f"soft failure after {MAX_RETRIES} retries ({reason}): {batch}")
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


def main():
    parser = argparse.ArgumentParser(
        description='download music from spotify urls using spotdl'
    )
    parser.add_argument('--url-file', '-u', type=str)
    parser.add_argument('--output', '-o', type=str)
    parser.add_argument('--format', '-f', type=str, default='mp3')
    parser.add_argument('--bitrate', '-b', type=str, default='320k')
    parser.add_argument('--overwrite-errors', action='store_true')
    parser.add_argument('--skip-existing', action='store_true')
    parser.add_argument('--verbose', '-v', action='store_true')
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--batch-size', type=int, default=1)
    parser.add_argument('--pre-skip-existing', action='store_true')

    args = parser.parse_args()

    url_file = args.url_file
    if not url_file:
        export_dir = get_export_dir()
        url_file = os.path.join(export_dir, 'spotify_manifest_urls.txt')
        print(f"using default url file: {url_file}")

    try:
        success = download_music(
            url_file=url_file,
            output_dir=args.output,
            format=args.format,
            bitrate=args.bitrate,
            overwrite_errors=args.overwrite_errors,
            skip_existing=args.skip_existing,
            verbose=args.verbose,
            validate_only=args.validate_only,
            batch_size=args.batch_size,
            pre_skip_existing=args.pre_skip_existing,
        )
        if not success:
            sys.exit(1)
    except Exception as e:
        print(f"error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
