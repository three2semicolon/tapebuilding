#!/usr/bin/env python3
"""compile soft_failures.txt + failed_downloads.txt into a single retry list,
filtered against the existing library so only still-missing tracks remain.

optionally write a manual-hunt csv (--report-csv) of the remaining tracks with
artist, track, album, failure reason, the spotify url, and a clickable search
link, so you can source the stubborn ones by hand.

the failure logs are written by download_music._log_urls as `url  # reason` (or a
bare `url`), and a track can show up multiple times across/within both files -
sometimes as a soft reason (e.g. LookupError) and later as track_unavailable. so
urls are deduped and their reasons unioned; if track_unavailable appears for a
url at all it's treated as hard (genuinely gone) and excluded unless
--include-unavailable.

the existence check reuses download_music's exact matching path: read export csvs
for url -> (artist, track) metadata, predict the spotdl filename, normalize, and
look it up in the library index. matching this path keeps `retry_list.txt`
consistent with what `download --pre-skip-existing` would itself skip.

typical flow: run `download -u retry_list.txt`, then re-run this command - the
library check drops whatever the retry round just succeeded on, so the retry
list (and any --report-csv) reflects only what's still missing.
"""

import argparse
import csv
import glob
import os
import re
import sys
import urllib.parse
from collections import OrderedDict

from dotenv import load_dotenv

from download.download_music import _predict_output_filename
from download.spotify_utils import get_export_dir
from organize.library import resolve_library_root, build_library_index, _normalize

load_dotenv()

# reasons logged to failed_downloads.txt with this marker are tracks spotdl said
# no longer exist - retrying won't recover them, so they're excluded by default.
HARD_REASON = 'track_unavailable'

DEFAULT_FAILED = 'failed_downloads.txt'
DEFAULT_SOFT = 'soft_failures.txt'
DEFAULT_OUT = 'retry_list.txt'
DEFAULT_REPORT = 'retry_report.csv'

# `url  # reason` or a bare `url`; `\S+` captures the url, the optional group grabs
# the trailing reason after the `  # ` comment marker.
_LINE_RE = re.compile(r'^(\S+)(?:\s+#\s*(.*))?$')


def _parse_failure_file(path):
    """returns list of (url, reason) parsed from a failure log; missing file -> []."""
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            m = _LINE_RE.match(line.strip())
            if not m:
                continue
            url = m.group(1).strip()
            reason = (m.group(2) or '').strip()
            if url and not url.startswith('#'):
                entries.append((url, reason))
    return entries


def _collect_urls(*paths):
    """merge failure logs into an OrderedDict[url -> list(reasons)], first-seen order.
    reasons are unioned across/within files so a url that later hard-failed is flagged."""
    combined = OrderedDict()
    for path in paths:
        for url, reason in _parse_failure_file(path):
            reasons = combined.setdefault(url, [])
            if reason and reason not in reasons:
                reasons.append(reason)
    return combined


def _read_full_metadata_from_file(csv_path):
    """read one csv into url -> {artist, track, album}; first-seen wins per file.
    mirrors download_music._read_csv_metadata_from_file (same sniffer, same
    track_name + artist_names gate, same first-seen rule) but keeps album_name too,
    so the existence check stays byte-identical to `download --pre-skip-existing`
    while the report also gets an album column."""
    rows = {}
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
                if url and url not in rows:
                    rows[url] = {
                        'artist': (row.get('artist_names') or '').strip(),
                        'track': (row.get('track_name') or '').strip(),
                        'album': (row.get('album_name') or '').strip(),
                    }
    except Exception as e:
        print(f"warning: failed to read csv metadata from {csv_path}: {e}")
    return rows


def _read_full_metadata(source):
    """read export csv(s) into url -> {artist, track, album}; first-seen wins across
    files (mirrors download_music._read_csv_metadata). returns None if no usable csv
    has the track_name + artist_names columns."""
    if os.path.isdir(source):
        merged = {}
        for csv_path in glob.glob(os.path.join(source, '*.csv')):
            for url, val in _read_full_metadata_from_file(csv_path).items():
                if url not in merged:
                    merged[url] = val
        return merged if merged else None
    elif source.lower().endswith('.csv'):
        result = _read_full_metadata_from_file(source)
        return result if result else None
    return None


def _filter_existing(urls, metadata, library_index, fmt):
    """split urls into (retry, already_on_disk, no_metadata) using the same matching
    path as download_music's --pre-skip-existing: predict the spotdl filename from
    export csv metadata, normalize the stem, look it up in the library index."""
    retry = []
    on_disk = []
    no_meta = []
    for url in urls:
        m = metadata.get(url) or {}
        artist = m.get('artist', '')
        title = m.get('track', '')
        if not artist or not title:
            # can't predict a filename without metadata - include it (safe; spotdl
            # re-checks) and flag it so the summary accounts for the unknown.
            no_meta.append(url)
            retry.append(url)
            continue
        stem = os.path.splitext(_predict_output_filename(artist, title, fmt))[0]
        if _normalize(stem) in library_index:
            on_disk.append(url)
        else:
            retry.append(url)
    return retry, on_disk, no_meta


def _youtube_search_url(artist, track):
    """clickable youtube results link for manual sourcing; empty if no names."""
    q = f"{artist} {track}".strip()
    if not q:
        return ''
    return 'https://www.youtube.com/results?search_query=' + urllib.parse.quote(q)


def _write_urls(path, urls):
    with open(path, 'w', encoding='utf-8') as f:
        for url in urls:
            f.write(url + '\n')


def _write_report(path, urls, combined, metadata):
    """write a manual-hunt csv - columns: artist, track, album, reason, spotify_url,
    search - sorted by artist, then album, then track (rows with no artist sink last
    so the identified ones you can act on come first). returns how many rows actually
    got names (the rest had no metadata and are url-only)."""
    rows = []
    named = 0
    for url in urls:
        m = metadata.get(url) or {}
        artist = (m.get('artist') or '').strip()
        track = (m.get('track') or '').strip()
        album = (m.get('album') or '').strip()
        if artist or track:
            named += 1
        rows.append({
            'artist': artist,
            'track': track,
            'album': album,
            'reason': ', '.join(combined.get(url, [])),
            'url': url,
            'search': _youtube_search_url(artist, track),
        })
    rows.sort(key=lambda r: (
        not bool(r['artist']),   # named artists first, unnamed sink to the bottom
        r['artist'].lower(),
        r['album'].lower(),
        r['track'].lower(),
    ))
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['artist', 'track', 'album', 'reason', 'spotify_url', 'search'])
        for r in rows:
            writer.writerow([r['artist'], r['track'], r['album'], r['reason'],
                             r['url'], r['search']])
    return named


def build_retry_list(failed_path, soft_path, output_path, metadata_source,
                     library_root, fmt, include_unavailable=False,
                     no_check=False, verbose=False, report_path=None):
    combined = _collect_urls(soft_path, failed_path)
    n_combined = len(combined)
    print(f"combined failure logs:")
    print(f"  soft                  : {soft_path}")
    print(f"  failed                : {failed_path}")
    print(f"  unique urls (combined): {n_combined}")

    hard = [u for u, r in combined.items() if HARD_REASON in r]
    queue = OrderedDict()
    for url, reasons in combined.items():
        if not include_unavailable and HARD_REASON in reasons:
            continue
        queue[url] = reasons

    if hard:
        status = 'excluded' if not include_unavailable else 'included'
        print(f"  unavailable (hard)    : {len(hard)} ({status} - use "
              f"{'--include-unavailable' if not include_unavailable else 'default'} "
              f"to {'add' if not include_unavailable else 'drop'} them)")

    if not queue:
        print("nothing left to retry.")
        _write_urls(output_path, [])
        if report_path:
            print("(report not written - nothing to retry)")
        return True

    # read metadata whenever we need it: always for the existence check, and also
    # for --report-csv even under --no-check (names come from here, not the library).
    metadata = None
    if not no_check or report_path:
        metadata = _read_full_metadata(metadata_source)

    if no_check:
        retry = list(queue.keys())
        on_disk = []
        no_meta = []
        print("existence check: skipped (--no-check)")
    else:
        if metadata is None:
            print("existence check: skipped - no csv metadata found "
                  f"at {metadata_source!r}")
            print("            run `export` (or pass --metadata <dir-or-csv>) to enable.")
            retry = list(queue.keys())
            on_disk = []
            no_meta = []
        else:
            library_index = build_library_index(library_root)
            print(f"existence check against: {library_root} ({len(library_index)} audio files)")
            retry, on_disk, no_meta = _filter_existing(queue, metadata, library_index, fmt)

    _write_urls(output_path, retry)

    print(f"\nresults:")
    print(f"  already on disk (skipped): {len(on_disk)}")
    print(f"  no metadata (kept)        : {len(no_meta)}")
    print(f"  hard excluded             : {len(hard) if not include_unavailable else 0}")
    print(f"  retry list                : {len(retry)}  -> {output_path}")

    if report_path:
        if metadata is None:
            print(f"\nreport: not written - no csv metadata to resolve names from "
                  f"{metadata_source!r}")
            print("        pass --metadata <dir-or-csv> with track_name + artist_names columns.")
        elif not retry:
            print("\nreport: nothing still missing - no rows to write.")
        else:
            named = _write_report(report_path, retry, combined, metadata)
            print(f"\nreport: {report_path} ({len(retry)} rows, {named} with names, "
                  f"{len(retry) - named} without)")
            print(f"        sorted by artist, then album; columns: artist, track, "
                  f"album, reason, spotify_url, search")

    if verbose:
        if hard and not include_unavailable:
            print("\nunavailable (excluded):")
            for u in hard:
                print(f"  {u}  # {', '.join(combined[u])}")
        if on_disk:
            print("\nalready on disk:")
            for u in on_disk:
                print(f"  {u}  # {', '.join(combined[u])}")
        if retry:
            print("\nto retry:")
            for u in retry:
                print(f"  {u}  # {', '.join(combined.get(u, []))}")

    if retry:
        print(f"\nnext: download -u {output_path}")
    else:
        print("\nnothing to retry - all failures are unavailable or already downloaded.")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='compile soft_failures + failed_downloads into a '
                    'library-filtered retry list (bare urls, one per line).'
    )
    parser.add_argument('--failed', default=DEFAULT_FAILED,
                        help=f'hard-failure log (default: {DEFAULT_FAILED})')
    parser.add_argument('--soft', default=DEFAULT_SOFT,
                        help=f'soft-failure log (default: {DEFAULT_SOFT})')
    parser.add_argument('-o', '--output', default=DEFAULT_OUT,
                        help=f'output file (default: {DEFAULT_OUT})')
    parser.add_argument('--metadata', default=None,
                        help='export dir or csv with track_name/artist_names '
                             'columns for the existence check (default: export dir)')
    parser.add_argument('--library', default=None,
                        help='library root to check against (default: archive_path)')
    parser.add_argument('-f', '--format', default='mp3',
                        help='spotdl format; doesn\'t affect the existence check '
                             '(the filename stem is matched, not the extension)')
    parser.add_argument('--include-unavailable', action='store_true',
                        help='include track_unavailable (hard) urls; excluded by default')
    parser.add_argument('--no-check', action='store_true',
                        help='skip the existence check, just combine + dedupe + categorize')
    parser.add_argument('--report-csv', dest='report_path', nargs='?',
                        const=DEFAULT_REPORT, default=None,
                        help=f'write a manual-hunt csv (artist/track/album/reason/'
                             f'spotify_url/search) for the remaining tracks - the '
                             f'"still missing" set after the library check. '
                             f'default name if flag given alone: {DEFAULT_REPORT}')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='print urls grouped by category')
    args = parser.parse_args()

    metadata_source = args.metadata or get_export_dir()
    library_root = args.library or resolve_library_root()

    try:
        ok = build_retry_list(
            failed_path=args.failed,
            soft_path=args.soft,
            output_path=args.output,
            metadata_source=metadata_source,
            library_root=library_root,
            fmt=args.format,
            include_unavailable=args.include_unavailable,
            no_check=args.no_check,
            verbose=args.verbose,
            report_path=args.report_path,
        )
        sys.exit(0 if ok else 1)
    except Exception as e:
        print(f"error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
