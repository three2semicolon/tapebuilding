"""compile soft_failures.txt + failed_downloads.txt into a single retry list,
filtered against the existing library so only still-missing tracks remain.

optionally write a manual-hunt csv (--report-csv) of the remaining tracks with
artist, track, album, failure reason, the spotify url, and a clickable search
link, so you can source the stubborn ones by hand.

the failure logs are written by download_spotify._log_urls as `url  # reason` (or a
bare `url`), and a track can show up multiple times across/within both files -
sometimes as a soft reason (e.g. LookupError) and later as track_unavailable. so
urls are deduped and their reasons unioned; if track_unavailable appears for a
url at all it's treated as hard (genuinely gone) and excluded unless
--include-unavailable.

the existence check reuses download_spotify's exact matching path: read export csvs
for url -> (artist, track) metadata, predict the spotdl filename, normalize, and
look it up in the library index. matching this path keeps `retry_list.txt`
consistent with what `spotify --pre-skip-existing` would itself skip.

typical flow: run `spotify -u retry_list.txt`, then re-run this command - the
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

from download.download_spotify import _predict_output_filename
from download.spotify_utils import get_export_dir
from organize.library import resolve_library_root, build_library_index, _normalize

# reasons logged to failed_downloads.txt with this marker are tracks spotdl said
# no longer exist - retrying won't recover them, so they're excluded by default.
HARD_REASON = 'track_unavailable'

DEFAULT_FAILED = 'failed_downloads.txt'
DEFAULT_SOFT = 'soft_failures.txt'
DEFAULT_OUT = 'retry_list.txt'
DEFAULT_REPORT = 'retry_report.csv'