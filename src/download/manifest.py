"""download.manifest - shared csv-metadata reading and spotdl filename
prediction, used by spotify_download.py (existence checks) and retry.py
(the same exact-match path, so retry stays consistent with what
`spotify --pre-skip-existing` would itself skip).

consolidates what used to be two independent near-identical copies: the
csv-sniffing/metadata reader here started as spotify_download.py's
pre-refactor _read_csv_metadata_from_file()/_read_csv_metadata(), and
retry.py carried its own second copy of the same logic before this module
existed. predict_output_filename() replaces the old sanitize_filename() +
_predict_output_filename() pair - the sanitization has to match spotdl's
own exactly, since predicted filenames are compared against what spotdl
actually writes to disk.

one change from the old tuple-returning version: metadata values are now
dicts ({'artist', 'track', 'album'}) instead of (artist, track) tuples,
since retry.py's --report-csv needs an album field the old shape didn't
carry.
"""

import csv
import glob
import os
import re


def sanitize_filename(filename):
    """strip characters spotdl's own output-writer strips, so a predicted
    filename matches whatever spotdl actually writes to disk."""
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    filename = filename.strip('. ')
    return filename


def predict_output_filename(artist_names, track_name, fmt):
    """predict the filename spotdl will write for (artist_names, track_name)
    at the given format extension, e.g. 'Artist - Title.mp3'."""
    return sanitize_filename(f"{artist_names} - {track_name}.{fmt}")


def read_csv_metadata_from_file(csv_path):
    """read one csv -> dict url -> {'artist', 'track', 'album'}. requires
    track_name/artist_names columns; if either is missing from the csv's
    header, returns {} for this file entirely (matches the old
    all-or-nothing behavior rather than partially trusting a malformed
    csv)."""
    metadata = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            sample = f.read(1024)
            f.seek(0)
            delimiter = csv.Sniffer().sniff(sample).delimiter
            reader = csv.DictReader(f, delimiter=delimiter)
            if reader.fieldnames:
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
            fieldnames = set(reader.fieldnames or [])
            if not {'track_name', 'artist_names'}.issubset(fieldnames):
                return {}
            for row in reader:
                url = (row.get('spotify_url') or '').strip()
                if not url or url in metadata:
                    continue
                metadata[url] = {
                    'artist': (row.get('artist_names') or '').strip(),
                    'track': (row.get('track_name') or '').strip(),
                    'album': (row.get('album_name') or row.get('album') or '').strip(),
                }
    except Exception as e:
        print(f"warning: failed to read csv metadata from {csv_path}: {e}")
    return metadata


def read_csv_metadata(url_file):
    """read csv metadata from a single csv file, or every csv in a
    directory (first-seen-wins across files, matching
    spotify_download.py's own url-collection order) -> dict url ->
    {'artist', 'track', 'album'}.

    always returns a dict, never None - callers check truthiness
    ("no csvs with usable metadata found") rather than an `is None` check.
    """
    merged = {}
    if os.path.isdir(url_file):
        for csv_path in glob.glob(os.path.join(url_file, '*.csv')):
            for url, meta in read_csv_metadata_from_file(csv_path).items():
                merged.setdefault(url, meta)
    elif url_file.lower().endswith('.csv'):
        merged.update(read_csv_metadata_from_file(url_file))
    return merged
