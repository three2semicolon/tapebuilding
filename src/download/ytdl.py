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


def download_ytdl(url, output_dir=None, audio_format='mp3', audio_quality='0',
                        embed_thumbnail=True, overwrite=False, verbose=False,
                        metadata_only=False, cookies_from_browser=None, ffmpeg_path=None):
    try:
        import yt_dlp
    except ImportError:
        print("error: yt-dlp not installed. run: pip install yt-dlp")
        return False

    final_output_dir = resolve_output_dir(output_dir)
    print(f"saving to: {final_output_dir}")

    if metadata_only:
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

    tmpl = OUTTMPL_PLAYLIST if is_playlist_url(url) else OUTTMPL_SINGLE
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

    ffmpeg = ffmpeg_path or resolve_ffmpeg_path()
    if ffmpeg:
        ydl_opts['ffmpeg_location'] = ffmpeg

    if cookies_from_browser:
        ydl_opts['cookiesfrombrowser'] = (cookies_from_browser,)

    print(f"downloading: {url}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.download([url])
        return result == 0
    except Exception as e:
        print(f"error during download: {e}")
        return False
