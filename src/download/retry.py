"""download.retry - compile soft_failures.txt + failed_downloads.txt into a
single retry list, filtered against the existing library so only
still-missing tracks remain.

**rebuilt from the README description** - retry_failures.py's real logic was
lost; only its docstring and constants survived (see PACKAGE_OVERVIEW.md /
TODO.md Phase 3). this is new code, written directly against lib/ and
download.existing/download.spotify_download - no old cross-package imports
to clean up.

optionally write a manual-hunt csv (--report-csv) of the remaining tracks
with artist, track, album, failure reason, the spotify url, and a clickable
youtube search link, so you can source the stubborn ones by hand.

the failure logs are written by spotify_download._log_urls as
`url  # reason` (or a bare `url`), and a track can show up multiple times
across/within both files - sometimes as a soft reason (e.g. LookupError) and
later as track_unavailable. so urls are deduped and their reasons unioned;
if track_unavailable appears for a url at all it's treated as hard
(genuinely gone) and excluded unless --include-unavailable.

the existence check reuses spotify_download's exact matching path: read
export csvs for url -> (artist, track, album) metadata, predict the spotdl
filename, normalize, and look it up in the library index (download.existing,
not lib.catalog - see that module's docstring for why they're different
checks). matching this path keeps retry_list.txt consistent with what
`spotify --pre-skip-existing` would itself skip. the csv-reading and
filename-prediction helpers themselves live in download.manifest - this
module used to carry its own second copy of spotify_download's csv-sniffing
logic, now consolidated (see manifest.py's docstring).

typical flow: run `spotify -u retry_list.txt`, then re-run this command -
the library check drops whatever the retry round just succeeded on, so the
retry list (and any --report-csv) reflects only what's still missing.
"""

import csv
import re
import os
import urllib.parse
from collections import OrderedDict

from lib.paths import archive_path
from lib.text import normalize_key
from download.existing import build_library_index
from download.spotify_api import get_export_dir
from download.manifest import predict_output_filename, read_csv_metadata

# reasons logged to failed_downloads.txt with this marker are tracks spotdl said
# no longer exist - retrying won't recover them, so they're excluded by default.
HARD_REASON = 'track_unavailable'

DEFAULT_FAILED = 'failed_downloads.txt'
DEFAULT_SOFT = 'soft_failures.txt'
DEFAULT_OUT = 'retry_list.txt'
DEFAULT_REPORT = 'retry_report.csv'

_LOG_LINE_RE = re.compile(r'^(?P<url>\S+)(?:\s+#\s*(?P<reason>.*))?$')


def read_failure_log(path):
    """parse one failure log -> OrderedDict url -> set(reasons) (insertion
    order preserved, empty set for a bare url with no logged reason)."""
    url_reasons = OrderedDict()
    if not os.path.exists(path):
        return url_reasons
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = _LOG_LINE_RE.match(line)
            if not m:
                continue
            url = m.group('url')
            reason = (m.group('reason') or '').strip()
            reasons = url_reasons.setdefault(url, set())
            if reason:
                reasons.add(reason)
    return url_reasons


def collect_failures(failed_path, soft_path):
    """union failed_downloads.txt + soft_failures.txt -> OrderedDict url ->
    set(reasons), deduped across both files."""
    merged = OrderedDict()
    for path in (failed_path, soft_path):
        for url, reasons in read_failure_log(path).items():
            merged.setdefault(url, set()).update(reasons)
    return merged


def write_retry_list(urls, path):
    with open(path, 'w', encoding='utf-8') as f:
        for url in urls:
            f.write(url + '\n')


def write_report_csv(rows, path):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['artist', 'track', 'album', 'reason', 'spotify_url', 'search'])
        writer.writeheader()
        writer.writerows(rows)


def run_retry(failed_path=DEFAULT_FAILED, soft_path=DEFAULT_SOFT,
              output_path=DEFAULT_OUT, include_unavailable=False,
              no_check=False, metadata_source=None, library_root=None,
              report_csv_path=None):
    """compile + (by default) re-check the retry list. returns a results
    dict - no printing here, that's cli.py's job (per the per-package
    cli.py split: plain functions report via return values, not print()).
    """
    url_reasons = collect_failures(failed_path, soft_path)
    total_seen = len(url_reasons)

    hard_excluded = []
    candidates = []
    for url, reasons in url_reasons.items():
        if HARD_REASON in reasons and not include_unavailable:
            hard_excluded.append(url)
        else:
            candidates.append(url)

    already_on_disk = []
    no_meta = []
    retry_urls = list(candidates)
    metadata = {}

    if not no_check:
        resolved_metadata_source = metadata_source or get_export_dir()
        metadata = read_csv_metadata(resolved_metadata_source)
        resolved_library_root = library_root or archive_path()
        library_index = build_library_index(resolved_library_root)

        retry_urls = []
        for url in candidates:
            meta = metadata.get(url)
            if not meta or not meta.get('artist') or not meta.get('track'):
                no_meta.append(url)
                retry_urls.append(url)  # can't verify without metadata - keep it, don't silently drop
                continue
            predicted = predict_output_filename(meta['artist'], meta['track'], 'mp3')
            stem = os.path.splitext(predicted)[0]
            if normalize_key(stem) in library_index:
                already_on_disk.append(url)
            else:
                retry_urls.append(url)

    write_retry_list(retry_urls, output_path)

    report_rows = []
    if report_csv_path:
        for url in retry_urls:
            meta = metadata.get(url, {})
            reasons = sorted(r for r in url_reasons.get(url, ()) if r)
            artist = meta.get('artist', '')
            track = meta.get('track', '')
            search_q = urllib.parse.quote(f"{artist} {track}".strip())
            report_rows.append({
                'artist': artist,
                'track': track,
                'album': meta.get('album', ''),
                'reason': ', '.join(reasons) or 'unknown',
                'spotify_url': url,
                'search': f"https://www.youtube.com/results?search_query={search_q}",
            })
        report_rows.sort(key=lambda r: (r['artist'].lower(), r['album'].lower(), r['track'].lower()))
        write_report_csv(report_rows, report_csv_path)

    return {
        'total_seen': total_seen,
        'hard_excluded': hard_excluded,
        'already_on_disk': already_on_disk,
        'no_meta': no_meta,
        'retry_urls': retry_urls,
        'report_rows': report_rows,
        'output_path': output_path,
        'report_csv_path': report_csv_path,
    }
