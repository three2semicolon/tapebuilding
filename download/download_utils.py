"""
download utilities for the tapebuilding project.
"""

import os
import subprocess
import sys
from dotenv import load_dotenv

load_dotenv()

def get_default_download_dir():
    """get the default download directory."""
    # check if archive_path is set in .env
    archive_path = os.getenv('archive_path')
    if archive_path:
        return archive_path

    # fallback to a default music directory
    return os.path.join(os.path.expanduser("~"), "music", "tapebuilding")

def download_with_spotdl(url_file, output_dir=None, format='mp3', bitrate='320k',
                        overwrite_errors=False, skip_existing=False, verbose=False):
    """download music using spotdl from a file of spotify urls."""
    # set default output directory if not provided
    if output_dir is None:
        output_dir = get_default_download_dir()

    # ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # build spotdl command
    cmd = ["spotdl"]

    # add url file
    cmd.extend(["--input-file", url_file])

    # add output directory if specified
    if output_dir:
        # create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        cmd.extend(["--output", output_dir])
    else:
        # use archive_path from .env or fallback
        archive_path = os.getenv('archive_path', os.path.expanduser('~/music/tapebuilding'))
        os.makedirs(archive_path, exist_ok=True)
        cmd.extend(["--output", archive_path])

    # add format and bitrate options
    cmd.extend([
        "--format", format,
        "--bitrate", bitrate
    ])

    # add optional flags
    if overwrite_errors:
        cmd.append("--overwrite-errors")
    if skip_existing:
        cmd.append("--skip-existing")
    if verbose:
        cmd.append("--verbose")

    print(f"downloading music from: {url_file}")
    print(f"saving to: {output_dir}")
    print(f"running: {' '.join(cmd)}")

    # run spotdl command
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False  # don't raise exception on non-zero exit
        )

        # print stdout and stderr
        if result.stdout:
            print(result.stdout.strip())
        if result.stderr:
            print(result.stderr.strip(), file=sys.stderr)

        if result.returncode == 0:
            print(f"\ndownload complete!")
            return True
        else:
            print(f"\ndownload failed with exit code {result.returncode}")
            return False

    except FileNotFoundError:
        print("error: spotdl not found. please install it with: uv add spotdl")
        return False
    except Exception as e:
        print(f"error running spotdl: {e}")
        return False

def validate_url_file(file_path):
    """validate that the url file exists and contains valid spotify urls."""
    if not os.path.exists(file_path):
        return False, f"file not found: {file_path}", 0

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        if not lines:
            return False, "url file is empty", 0

        # basic validation - check if lines look like spotify urls
        spotify_count = 0
        for line in lines:
            if 'open.spotify.com/track/' in line or 'open.spotify.com/album/' in line or 'open.spotify.com/playlist/' in line or 'spotify:track:' in line or 'spotify:album:' in line or 'spotify:playlist:' in line:
                spotify_count += 1

        if spotify_count == 0:
            return False, "no valid spotify urls found in file", len(lines)

        return True, f"found {spotify_count} valid spotify urls out of {len(lines)} lines", spotify_count

    except Exception as e:
        return False, f"error reading file: {e}", 0