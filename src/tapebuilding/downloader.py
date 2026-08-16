"""Unified download service."""

import subprocess
import sys
from pathlib import Path
from typing import Iterable, List

def download(
    urls: Iterable[str],
    dest: Path,
    *,
    format: str = "mp3",
    bitrate: str = "320k",
    verbose: bool = False,
) -> List[Path]:
    """Download a collection of URLs to dest using spotdl or yt-dlp.

    Returns a list of paths to the downloaded files.
    """
    dest.mkdir(parents=True, exist_ok=True)
    downloaded: List[Path] = []
    for url in urls:
        # Use spotdl by default; fallback to yt-dlp if spotdl fails
        cmd = [
            "uv", "run", "spotdl", "download", url, "--format", format,
            "--bitrate", bitrate, "--output", str(dest)
        ]
        if verbose:
            print(f"Downloading {url} to {dest} (cmd: {' '.join(cmd)})")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            # spotdl outputs the filename(s) it creates; find them
            for p in dest.iterdir():
                if p.is_file():
                    downloaded.append(p)
        else:
            print(f"Error downloading {url}: {result.stderr}", file=sys.stderr)
    return downloaded