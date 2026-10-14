"""download.fallback - fallback logic for when primary download methods fail.

Provides functions to handle fallback scenarios when spotdl or ytdl fail to
find/download a track, allowing users to specify alternative sources.
"""

import os
import shutil
import click
from typing import List, Dict, Any, Optional

from download.manifest import predict_output_filename
from download.existing import resolve_output_dir
from download.ytdl import OUTTMPL_PLAYLIST, OUTTMPL_SINGLE, is_playlist_url
from lib.paths import ffmpeg_path as resolve_ffmpeg_path
from lib.text import normalize_key
from organize.normalize_artists import normalize_artist


def _log_urls(filename: str, urls: List[str], reason: Optional[str] = None) -> None:
    """Log URLs to a failure file.

    Args:
        filename: Name of the file to log to
        urls: List of URLs to log
        reason: Optional reason for the failure
    """
    with open(filename, 'a', encoding='utf-8') as f:
        for url in urls:
            line = f"{url}  # {reason}" if reason else url
            f.write(line + '\n')


def process_fallback(
    batch: List[str],
    metadata: Dict[str, Dict[str, Any]],
    output_dir: str,
    format: str,
    overwrite_errors: bool,
    cookies_from_browser: Optional[str],
    resolved_ffmpeg: str,
    library_index: Optional[Dict[str, Any]] = None,
    is_spotify: bool = True
) -> tuple[List[str], List[str], bool]:
    """Process fallback for a batch of failed URLs.

    Args:
        batch: List of URLs that failed primary download attempt
        metadata: Metadata dictionary mapping URLs to track info
        output_dir: Directory to save downloaded/copied files
        format: Audio format for downloads
        overwrite_errors: Whether to overwrite existing files
        cookies_from_browser: Browser to get cookies from
        resolved_ffmpeg: Path to ffmpeg executable
        library_index: Index of existing files (for existence check)
        is_spotify: Whether processing Spotify (True) or SoundCloud (False) URLs

    Returns:
        Tuple of (successful_urls, failed_urls, batch_succeeded_via_fallback)
    """
    print(f"\nInitiating fallback for batch...")
    fallback_succeeded = []
    fallback_failed = []

    # Determine metadata keys based on service
    artist_key = 'artist' if is_spotify else 'uploader'
    track_key = 'track' if is_spotify else 'title'

    for url in batch:
        meta = metadata.get(url) or {}
        artist = meta.get(artist_key, '')
        track = meta.get(track_key, '')

        if not artist or not track:
            print(f"  Skipping fallback for URL with missing metadata: {url}")
            fallback_failed.append(url)
            continue

        # Normalize artist and track metadata for consistent formatting
        artist = normalize_artist(artist)
        track = normalize_artist(track)

        # Predict output filename
        if is_spotify:
            predicted = predict_output_filename(artist, track, format)
        else:
            # For SoundCloud, we need additional metadata
            set_name = meta.get('set_name', None)
            set_position = meta.get('set_position', None)
            if set_name and set_position is not None:
                # Playlist template
                predicted = f"{set_name}/{set_position:02d} - {artist} - {track}.{format}"
            else:
                # Single template
                predicted = f"{artist} - {track}.{format}"

        stem = os.path.splitext(predicted)[0]

        # Check if already exists via pre-skip logic (if enabled and library_index provided)
        if library_index is not None and normalize_key(stem) in library_index:
            print(f"  File already exists (via pre-skip): {predicted}")
            fallback_succeeded.append(url)
            continue

        # Prompt user for fallback source
        try:
            user_input = click.prompt(
                f"Enter a URL or local file path to download '{artist} - {track}' instead (or press Enter to skip)",
                default='', show_default=False
            )
        except (EOFError, click.exceptions.Abort):
            # Treat as empty input (skip)
            user_input = ''

        if not user_input:
            print(f"  Skipping fallback for '{artist} - {track}'.")
            fallback_failed.append(url)
            continue

        # Determine if input is a URL or file path
        if user_input.startswith(('http://', 'https://')):
            # Treat as URL, download via ytdl but use original metadata for naming
            print(f"  Downloading via ytdl from URL: {user_input}")

            # Prepare ytdl options
            final_output_dir = resolve_output_dir(output_dir)
            tmpl = OUTTMPL_PLAYLIST if is_playlist_url(user_input) else OUTTMPL_SINGLE
            outtmpl = os.path.join(final_output_dir, tmpl)

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': outtmpl,
                'quiet': True,  # verbose=False in fallback
                'verbose': False,
                'ignoreerrors': True,
                'nooverwrites': not overwrite_errors,
                'postprocessors': [],
            }

            if format != 'best':
                ydl_opts['postprocessors'].append({
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': format,
                    'preferredquality': '0',  # best VBR
                })

            ydl_opts['postprocessors'].append({
                'key': 'FFmpegMetadata',
                'add_metadata': True,
            })

            if True:  # embed_thumbnail - always embed in fallback for consistency
                ydl_opts['postprocessors'].append({'key': 'EmbedThumbnail'})
                ydl_opts['writethumbnail'] = True

            ffmpeg = resolved_ffmpeg or resolve_ffmpeg_path()
            if ffmpeg:
                ydl_opts['ffmpeg_location'] = ffmpeg

            if cookies_from_browser:
                ydl_opts['cookiesfrombrowser'] = (cookies_from_browser,)

            # Override the output template to use our predicted filename based on original metadata
            forced_outtmpl = os.path.join(final_output_dir, predict_output_filename(artist, track, format))
            ydl_opts['outtmpl'] = forced_outtmpl

            print(f"  Saving as: {predict_output_filename(artist, track, format)}")

            try:
                import yt_dlp
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.download([user_input])
                ytdl_success = result == 0
            except Exception as e:
                print(f"  error during download: {e}")
                ytdl_success = False

            if ytdl_success:
                print(f"  Successfully downloaded via ytdl.")
                fallback_succeeded.append(url)
            else:
                print(f"  ytdl download failed.")
                fallback_failed.append(url)
        else:
            # Treat as local file path
            if not os.path.exists(user_input):
                print(f"  Local file not found: {user_input}")
                fallback_failed.append(url)
                continue
            # Copy file to output directory with predicted filename
            try:
                shutil.copy2(user_input, os.path.join(output_dir, predicted))
                print(f"  Copied local file to: {predicted}")
                fallback_succeeded.append(url)
            except Exception as e:
                print(f"  Failed to copy local file: {e}")
                fallback_failed.append(url)

    # Determine if batch succeeded via fallback
    batch_succeeded_via_fallback = len(fallback_failed) == 0

    if fallback_failed:
        print(f"  Fallback failed for {len(fallback_failed)} URL(s) in batch.")
        # Log the failed URLs
        _log_urls('soft_failures.txt', fallback_failed, reason='fallback_failed')
    else:
        print(f"  All URLs in batch succeeded via fallback.")

    return fallback_succeeded, fallback_failed, batch_succeeded_via_fallback