"""CSV and manifest export utilities."""

import csv
from pathlib import Path
from typing import List, Dict

def write_csv(
    file_path: Path,
    rows: List[Dict],
    fieldnames: List[str],
    *,
    write_header: bool = True,
) -> None:
    """Write rows to a CSV file atomically."""
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    try:
        with tmp_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            if write_header:
                writer.writeheader()
            writer.writerows(rows)
        tmp_path.replace(file_path)
    except OSError as e:
        print(f"Warning: could not write {file_path}: {e}")

def write_manifest(
    file_path: Path,
    tracks: List[Dict],
    url_field: str = "spotify_url",
) -> None:
    """Write manifest of tracks with URLs to a .txt file."""
    with file_path.open("w", encoding="utf-8") as f:
        for track in tracks:
            url = track.get(url_field, "")
            if url:
                f.write(url + "\n")