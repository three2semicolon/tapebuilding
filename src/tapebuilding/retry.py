"""Generate and manage retry lists for failed downloads."""

import csv
import os
from pathlib import Path
from typing import List, Dict, Iterable

def load_failure_logs(failed_path: Path, soft_path: Path) -> List[Dict[str, List[str]]]:
    """Load failed and soft failure logs and merge them."""
    combined: Dict[str, List[str]] = {}
    for log_path in (failed_path, soft_path):
        if not log_path.exists():
            continue
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Parse "url [# reason]" format
                if "  # " in line:
                    url, reason = line.split("  # ", 1)
                else:
                    url = line
                    reason = ""
                url = url.strip()
                reason = reason.strip()
                if url:
                    if url not in combined:
                        combined[url] = []
                    if reason not in combined[url]:
                        combined[url].append(reason)
                else:
                    # Just a bare URL
                    if url not in combined:
                        combined[url] = [""]
    return list(combined.items())

def filter_existing(
    urls: Iterable[str],
    metadata_source: Path,
    fmt: str,
    library_index: Dict[str, None],
) -> tuple[List[str], List[str], List[str]]:
    """Filter URLs that already exist on disk, returning retry list, existing, no_meta."""
    retry_urls = []      # URLs that are NOT in the library index (need retry)
    on_disk = []         # URLs that ARE in the library index (already downloaded)
    no_meta = []         # URLs with no metadata (placeholder, currently unused)
    for url in urls:
        if url in library_index:
            on_disk.append(url)
        else:
            retry_urls.append(url)
    return retry_urls, on_disk, no_meta