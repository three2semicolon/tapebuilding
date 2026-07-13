import argparse
import os
import re
import sys

from dotenv import load_dotenv
from organize.library import resolve_library_root

load_dotenv()

# separate templates - the %(playlist&...)s conditional corrupts on Windows
# due to yt-dlp's null-byte handling in its format-string parser
OUTTMPL_SINGLE   = '%(uploader)s - %(title)s.%(ext)s'
OUTTMPL_PLAYLIST = '%(playlist)s/%(playlist_index)02d - %(uploader)s - %(title)s.%(ext)s'

AUDIO_FORMATS = ('mp3', 'm4a', 'opus', 'vorbis', 'wav', 'flac', 'alac', 'aac', 'best')

_PLAYLIST_RE = re.compile(r'/sets/|/albums/|/tracks/?$|/likes/?$|/reposts/?', re.IGNORECASE)


def is_playlist_url(url):
    return bool(_PLAYLIST_RE.search(url))


def _resolve_output_dir(output_dir, create=True):
    final = output_dir or resolve_library_root()
    if create:
        os.makedirs(final, exist_ok=True)
    return final


def download_ytdl(url, output_dir=None, audio_format='mp3', audio_quality='0',
                        embed_thumbnail=True, overwrite=False, verbose=False,
                        metadata_only=False, cookies_from_browser=None, ffmpeg_path=None):
    try:
        import yt_dlp
    except ImportError:
        print("error: yt-dlp not installed. run: pip install yt-dlp")
        return False

    final_output_dir = _resolve_output_dir(output_dir)
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

    ffmpeg = ffmpeg_path or os.getenv('FFMPEG_PATH') or os.getenv('ffmpeg_path')
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


def main():
    parser = argparse.ArgumentParser(
        description='download a track, set/playlist, or album from any yt-dlp-supported '
                    'source (soundcloud, youtube, ...) via yt-dlp'
    )
    parser.add_argument('url', type=str)
    parser.add_argument('-o', '--output', type=str)
    parser.add_argument('-f', '--format', type=str, default='mp3', choices=AUDIO_FORMATS)
    parser.add_argument('-q', '--audio-quality', type=str, default='0')
    parser.add_argument('--no-thumbnail', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-m', '--metadata-only', action='store_true')
    parser.add_argument('--cookies-from-browser', type=str)
    parser.add_argument('--ffmpeg', type=str)

    args = parser.parse_args()

    try:
        success = download_ytdl(
            url=args.url,
            output_dir=args.output,
            audio_format=args.format,
            audio_quality=args.audio_quality,
            embed_thumbnail=not args.no_thumbnail,
            overwrite=args.overwrite,
            verbose=args.verbose,
            metadata_only=args.metadata_only,
            cookies_from_browser=args.cookies_from_browser,
            ffmpeg_path=args.ffmpeg,
        )
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
