"""download.ytdl - download a track, set/playlist, or album from any
yt-dlp-supported source (soundcloud, youtube, ...).

was yt_dlp_downloader.py. changes beyond the cli.py split:
- organize.library.resolve_library_root() -> download.existing.resolve_output_dir()
  (was independently duplicated here as its own _resolve_output_dir - now
  the one copy shared with spotify_download.py, see download/existing.py)
- the FFMPEG_PATH/ffmpeg_path dual-case getenv -> lib.paths.ffmpeg_path()
  (dual-case fallback dropped project-wide, see REFACTOR_PLAN.md). imported
  under an alias since download_ytdl()'s own `ffmpeg_path` parameter (the
  CLI's explicit --ffmpeg override) would otherwise shadow it.
"""

import os
import re

from lib.paths import ffmpeg_path as resolve_ffmpeg_path
from download.existing import resolve_output_dir

# separate templates - the %(playlist&...)s conditional corrupts on Windows
# due to yt-dlp's null-byte handling in its format-string parser
OUTTMPL_SINGLE   = '%(uploader)s - %(title)s.%(ext)s'
OUTTMPL_PLAYLIST = '%(playlist)s/%(playlist_index)02d - %(uploader)s - %(title)s.%(ext)s'

AUDIO_FORMATS = ('mp3', 'm4a', 'opus', 'vorbis', 'wav', 'flac', 'alac', 'aac', 'best')

_PLAYLIST_RE = re.compile(r'/sets/|/albums/|/tracks/?$|/likes/?$|/reposts/?', re.IGNORECASE)


def is_playlist_url(url):
    return bool(_PLAYLIST_RE.search(url))


def _check_ytdl_availability():
    """Check if yt-dlp is available.

    Returns:
        yt_dlp module if available, False otherwise
    """
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        print("error: yt-dlp not installed. run: pip install yt-dlp")
        return False


def _resolve_and_display_output_dir(output_dir):
    """Resolve and display the output directory.

    Args:
        output_dir: Output directory path (can be None)

    Returns:
        Resolved output directory path
    """
    final_output_dir = resolve_output_dir(output_dir)
    print(f"saving to: {final_output_dir}")
    return final_output_dir


def _handle_metadata_only(url, audio_format, audio_quality, embed_thumbnail,
                          verbose, cookies_from_browser):
    """Handle metadata-only mode.

    Args:
        url: URL to extract metadata from
        audio_format: Audio format (unused in metadata-only mode)
        audio_quality: Audio quality (unused in metadata-only mode)
        embed_thumbnail: Whether to embed thumbnail (unused in metadata-only mode)
        verbose: Whether to run in verbose mode
        cookies_from_browser: Cookies from browser option

    Returns:
        Boolean success status
    """
    yt_dlp = _check_ytdl_availability()
    if not yt_dlp:
        return False

    flat_opts = {
        'quiet': not verbose,
        'verbose': verbose,
        'extract_flat': True,
    }
    if cookies_from_browser:
        flat_opts['cookiesfrombrowser'] = (cookies_from_browser,)

    print(f"metadata for: {url}")
    with yt_dlp.YoutubeDL(flat_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info:
            entries = info.get('entries', [info])
            for i, entry in enumerate(entries, 1):
                title = entry.get('title', 'Unknown')
                print(f"{i}. {title}" if is_playlist_url(url) else title)
    return True


def _get_output_template(url):
    """Get the appropriate output template based on URL type.

    Args:
        url: URL to check

    Returns:
        Output template string
    """
    tmpl = OUTTMPL_PLAYLIST if is_playlist_url(url) else OUTTMPL_SINGLE
    return tmpl


def _resolve_ffmpeg_path(ffmpeg_path):
    """Resolve FFmpeg path from parameter or default.

    Args:
        ffmpeg_path: FFmpeg path parameter (can be None)

    Returns:
        Resolved FFmpeg path or None
    """
    return ffmpeg_path or resolve_ffmpeg_path()


def _handle_cookies_option(ydl_opts, cookies_from_browser):
    """Handle cookies option in ydl_opts.

    Args:
        ydl_opts: YoutubeDL options dictionary to modify
        cookies_from_browser: Cookies from browser option
    """
    if cookies_from_browser:
        ydl_opts['cookiesfrombrowser'] = (cookies_from_browser,)


def _build_ydl_opts(final_output_dir, tmpl, audio_format, audio_quality,
                   embed_thumbnail, verbose, overwrite, cookies_from_browser, ffmpeg_path):
    """Build youtube-dl options dictionary.

    Args:
        final_output_dir: Output directory path
        tmpl: Output template string
        audio_format: Audio format
        audio_quality: Audio quality
        embed_thumbnail: Whether to embed thumbnail
        verbose: Whether to run in verbose mode
        overwrite: Whether to overwrite existing files
        cookies_from_browser: Cookies from browser option
        ffmpeg_path: FFmpeg path parameter

    Returns:
        Configured youtube-dl options dictionary
    """
    outtmpl = os.path.join(final_output_dir, tmpl)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': outtmpl,
        'quiet': not verbose,
        'verbose': verbose,
        'ignoreerrors': True,
        'nooverwrites': not overwrite,
        'postprocessors': [],
    }

    if audio_format != 'best':
        ydl_opts['postprocessors'].append({
            'key': 'FFmpegExtractAudio',
            'preferredcodec': audio_format,
            'preferredquality': audio_quality,
        })

    ydl_opts['postprocessors'].append({
        'key': 'FFmpegMetadata',
        'add_metadata': True,
    })

    if embed_thumbnail:
        ydl_opts['postprocessors'].append({'key': 'EmbedThumbnail'})
        ydl_opts['writethumbnail'] = True

    ffmpeg = _resolve_ffmpeg_path(ffmpeg_path)
    if ffmpeg:
        ydl_opts['ffmpeg_location'] = ffmpeg

    _handle_cookies_option(ydl_opts, cookies_from_browser)

    return ydl_opts


def _execute_download(url, ydl_opts):
    """Execute the download with error handling.

    Args:
        url: URL to download
        ydl_opts: YoutubeDL options dictionary

    Returns:
        Boolean success status
    """
    print(f"downloading: {url}")

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.download([url])
        return result == 0
    except Exception as e:
        print(f"error during download: {e}")
        return False


def download_ytdl(url, output_dir=None, audio_format='mp3', audio_quality='0',
                        embed_thumbnail=True, overwrite=False, verbose=False,
                        metadata_only=False, cookies_from_browser=None, ffmpeg_path=None):
    """download a track, set/playlist, or album from any
    yt-dlp-supported source (soundcloud, youtube, ...).

    was yt_dlp_downloader.py. changes beyond the cli.py split:
    - organize.library.resolve_library_root() -> download.existing.resolve_output_dir()
      (was independently duplicated here as its own _resolve_output_dir - now
      the one copy shared with spotify_download.py, see download/existing.py)
    - the FFMPEG_PATH/ffmpeg_path dual-case getenv -> lib.paths.ffmpeg_path()
      (dual-case fallback dropped project-wide, see REFACTOR_PLAN.md). imported
      under an alias since download_ytdl()'s own `ffmpeg_path` parameter (the
      CLI's explicit --ffmpeg override) would otherwise shadow it.
    """
    # Check yt-dlp availability
    yt_dlp = _check_ytdl_availability()
    if not yt_dlp:
        return False

    # Resolve and display output directory
    final_output_dir = _resolve_and_display_output_dir(output_dir)

    # Handle metadata-only mode
    if metadata_only:
        return _handle_metadata_only(url, audio_format, audio_quality, embed_thumbnail,
                                   verbose, cookies_from_browser)

    # Get output template based on URL type
    tmpl = _get_output_template(url)

    # Build youtube-dl options
    ydl_opts = _build_ydl_opts(final_output_dir, tmpl, audio_format, audio_quality,
                              embed_thumbnail, verbose, overwrite, cookies_from_browser, ffmpeg_path)

    # Execute download
    return _execute_download(url, ydl_opts)
