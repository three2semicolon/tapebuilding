"""
download music from Spotify URLs using spotDL.
"""

import argparse
import os
import sys
import subprocess
import csv
import re
from .spotify_utils import get_export_dir


def sanitize_filename(filename):
    """sanitize filename to match spotdl's default behavior (remove invalid characters)."""
    # remove invalid characters for Windows and POSIX
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    # remove trailing spaces and dots (Windows does not allow trailing dots or spaces)
    filename = filename.strip('. ')
    return filename


def download_music(url_file, output_dir=None, format='mp3', bitrate='320k',
                   overwrite_errors=False, skip_existing=False, verbose=False,
                   validate_only=False, batch_size=1, pre_skip_existing=False):
    """download music using spotDL from Spotify URLs (file, csv, or directory), processing in batches."""
    print(f"processing spotify source: {url_file}")

    if not os.path.exists(url_file):
        print(f"error: url file/path not found: {url_file}")
        return False

    urls = []
    try:
        if os.path.isdir(url_file):
            import glob
            csv_files = glob.glob(os.path.join(url_file, '*.csv'))
            if not csv_files:
                print(f"no CSV files found in directory: {url_file}")
                return False
            for csv_file in csv_files:
                print(f"  reading URLs from: {os.path.basename(csv_file)}")
                urls.extend(_extract_urls_from_csv(csv_file))
        elif url_file.lower().endswith('.csv'):
            urls = _extract_urls_from_csv(url_file)
        else:
            # treat as plain text file (one URL per line)
            with open(url_file, 'r', encoding='utf-8') as f:
                urls = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"error reading url source: {e}")
        return False

    # deduplicate while preserving order
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

    if validate_only:
        print(f"url validation complete: {url_count} unique URLs. "
              "Use without --validate-only to download.")
        return True

    # If we want to pre-skip existing files and we have a CSV with metadata, do that now
    if pre_skip_existing and url_file.lower().endswith('.csv'):
        try:
            with open(url_file, 'r', encoding='utf-8') as f:
                sample = f.read(1024)
                f.seek(0)
                sniffer = csv.Sniffer()
                delimiter = sniffer.sniff(sample).delimiter
                reader = csv.DictReader(f, delimiter=delimiter)
                if reader.fieldnames:
                    reader.fieldnames = [name.strip() for name in reader.fieldnames]
                required_columns = {'track_name', 'artist_names'}
                if not required_columns.issubset(set(reader.fieldnames)):
                    print("warning: CSV missing required columns for pre-skip (track_name, artist_names). "
                          "Falling back to standard processing.")
                else:
                    if output_dir:
                        os.makedirs(output_dir, exist_ok=True)
                        final_output_dir = output_dir
                    else:
                        archive_path = os.getenv('archive_path', os.path.expanduser('~/music/tapebuilding'))
                        os.makedirs(archive_path, exist_ok=True)
                        final_output_dir = archive_path

                    extension = format  # assuming format maps directly to extension (e.g., mp3 -> .mp3)
                    # spotdl's default output template is: {artists} - {title}
                    skipped_count = 0
                    new_urls = []
                    for row in reader:
                        url = row.get('spotify_url', '').strip()
                        if not url:
                            continue
                        track_name = row.get('track_name', '').strip()
                        artist_names = row.get('artist_names', '').strip()
                        if not track_name or not artist_names:
                            new_urls.append(url)
                            continue

                        filename = f"{artist_names} - {track_name}.{extension}"
                        filename = sanitize_filename(filename)
                        filepath = os.path.join(final_output_dir, filename)

                        if os.path.exists(filepath):
                            skipped_count += 1
                            if verbose:
                                print(f"skipping existing file: {filename}")
                        else:
                            new_urls.append(url)

                    print(f"pre-skip check: skipped {skipped_count} existing files, {len(new_urls)} to download.")
                    urls = new_urls
                    url_count = len(urls)
                    if url_count == 0:
                        print("all files already exist!")
                        return True
        except Exception as e:
            print(f"warning: failed to pre-skip existing files: {e}")
            print("falling back to standard processing.")

    # process URLs in batches
    overall_success = True
    num_batches = (url_count + batch_size - 1) // batch_size
    print(f"processing {url_count} URLs in {num_batches} batch(es) of up to {batch_size}")

    for batch_idx in range(num_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, url_count)
        batch = urls[start:end]
        batch_num = batch_idx + 1
        print(f"\n--- Batch {batch_num}/{num_batches} ({len(batch)} URLs) ---")

        # build spotdl command: operation, then URLs, then options
        cmd = [sys.executable, "-m", "spotdl", "download"] + batch
        cmd.extend([
            "--format", format,
            "--bitrate", bitrate
        ])

        if overwrite_errors:
            cmd.append("--overwrite")
        if skip_existing:
            cmd.append("--skip-existing")
        if verbose:
            cmd.append("--verbose")

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            cmd.extend(["--output", output_dir])
        else:
            archive_path = os.getenv('archive_path', os.path.expanduser('~/music/tapebuilding'))
            os.makedirs(archive_path, exist_ok=True)
            cmd.extend(["--output", archive_path])

        ffmpeg_path = os.getenv('ffmpeg_path')
        if ffmpeg_path:
            cmd.extend(["--ffmpeg", ffmpeg_path])

        print(f"running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False  # don't raise exception on non-zero exit
            )

            if result.stdout:
                print(result.stdout.strip())
            if result.stderr:
                print(result.stderr.strip(), file=sys.stderr)

            if result.returncode == 0:
                print(f"batch {batch_num} completed successfully")
            else:
                print(f"batch {batch_num} failed with exit code {result.returncode}")
                overall_success = False
        except Exception as e:
            print(f"error running spotdl for batch {batch_num}: {e}")
            overall_success = False

    if overall_success:
        print(f"\nAll batches processed successfully! total tracks processed: {url_count}")
    else:
        print(f"\nCompleted with errors; see output above.")
    return overall_success


def _extract_urls_from_csv(csv_path):
    """extract Spotify URLs from a CSV file (expects 'spotify_url' column)."""
    import csv
    urls = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get('spotify_url')
                if url and url.strip():
                    urls.append(url.strip())
    except Exception as e:
        print(f"warning: failed to read CSV {csv_path}: {e}")
    return urls


def main():
    """main cli function."""
    parser = argparse.ArgumentParser(
        description='download music from spotify urls using spotdl'
    )
    parser.add_argument('--url-file', '-u', type=str,
                        help='path to text file containing spotify urls (one per line)')
    parser.add_argument('--output', '-o', type=str,
                        help='output directory for downloaded music')
    parser.add_argument('--format', '-f', type=str, default='mp3',
                        help='audio format (default: mp3)')
    parser.add_argument('--bitrate', '-b', type=str, default='320k',
                        help='audio bitrate (default: 320k)')
    parser.add_argument('--overwrite-errors', action='store_true',
                        help='re-download files that had errors in previous attempts')
    parser.add_argument('--skip-existing', action='store_true',
                        help='skip files that already exist in output directory')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='enable verbose output')
    parser.add_argument('--validate-only', action='store_true',
                        help='only validate the url file without downloading')
    parser.add_argument('--batch-size', type=int, default=1,
                        help='number of URLs to process in each batch (default: 1)')
    parser.add_argument('--pre-skip-existing', action='store_true',
                        help='pre-check output directory for existing files and skip download if file exists (requires CSV with track_name and artist_names)')

    args = parser.parse_args()

    url_file = None
    if args.url_file:
        url_file = args.url_file
    else:
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
            pre_skip_existing=args.pre_skip_existing
        )
        if not success:
            sys.exit(1)
    except Exception as e:
        print(f"error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()