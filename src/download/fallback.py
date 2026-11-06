"""download.fallback - fallback logic for when primary download methods fail.

Provides functions to handle fallback scenarios when spotdl or ytdl fail to
find/download a track, allowing users to specify alternative sources.

In manual mode, the user is prompted for each failed track. They can:
- Enter a URL or local file path to download the track from an alternative source
- Press Enter to skip the track (it stays in unmatched.csv for future runs)
- Press Backspace to mark the track as lost
"""

import csv
import os
import sys
import shutil
import click
from datetime import date
from typing import List, Dict, Any, Optional, Tuple

from download.manifest import predict_output_filename
from download.ytdl import download_ytdl
from lib.text import normalize_key
from lib.paths import archive_path
from lib.catalog import links as manual_links
from download.existing import resolve_output_dir


def _read_key() -> Optional[str]:
    """Read a single keypress from the terminal.

    Returns the character as a string, or None for special keys (arrows,
    function keys) that can't be meaningfully interpreted, or None when
    stdin is not a TTY (non-interactive: fall back to click.prompt).
    """
    if not sys.stdin.isatty():
        return None

    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b'\x00', b'\xe0'):  # function/arrow key prefix
            msvcrt.getch()  # consume the scan code
            return None
        try:
            return ch.decode('utf-8')
        except UnicodeDecodeError:
            return ch.decode('latin-1')
    else:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch


def _url_slug(url: str) -> str:
    """Derive a filename-friendly slug from a URL's last path component.

    Used as a fallback identifier when csv metadata is missing (e.g.
    SoundCloud API-v2 tracks where yt-dlp couldn't extract title/uploader).
    """
    if not url:
        return ''
    return url.rstrip('/').split('/')[-1]


def _resolve_fallback_display(url, metadata, format):
    """Resolve display values and predicted filename for a fallback prompt.

    When csv metadata is missing (empty artist/track — common for SoundCloud
    API-v2 tracks where yt-dlp couldn't extract title/uploader), show the URL
    itself as the track identifier instead of skipping the prompt entirely.

    Returns (prompt_artist, prompt_track, predicted_filename, has_meta).
    """
    meta = metadata.get(url) or {}
    artist = meta.get('artist', '')
    track = meta.get('track', '')
    has_meta = bool(artist and track)
    if not has_meta:
        if not metadata:
            print("  Warning: no csv metadata was loaded at all (see the warning near the start of the run)")
        elif url not in metadata:
            print("  Warning: this url isn't in the loaded csv metadata (url mismatch?)")
        else:
            print(f"  Warning: missing artist/track metadata for {url}")
        predicted = f"{_url_slug(url) or 'unknown'}.{format}"
        return '', url, predicted, False
    return artist, track, predict_output_filename(artist, track, format), True


def _read_fallback_input(artist: str, track: str) -> Tuple[str, Optional[str]]:
    """Read user input for a fallback track, detecting backspace vs enter vs URL.

    The user can:
    - Type a URL or file path and press Enter  -> ('url', '<input>')
    - Press Enter on an empty line             -> ('skip', None)
    - Press Backspace on an empty line         -> ('lost', None)
    - Press Ctrl+C                             -> ('abort', None)

    Falls back to click.prompt when stdin is not a TTY (backspace not
    distinguishable from enter in that case; empty input = skip).

    Returns:
        Tuple of (action, value) where action is 'url', 'skip', 'lost', or
        'abort'.
    """
    result = _read_fallback_tty(artist, track)
    if result is not None:
        return result

    # Not a TTY: fall back to click.prompt for the whole line.
    prompt = (
        f"Enter a URL or local file path to download '{artist} - {track}' instead "
        f"(Enter to skip, Backspace to mark as lost): "
    )
    try:
        user_input = click.prompt(prompt.strip(), default='', show_default=False)
    except (EOFError, click.exceptions.Abort):
        return ('abort', None)
    if not user_input:
        return ('skip', None)
    return ('url', user_input)


def _read_fallback_tty(artist: str, track: str) -> Optional[Tuple[str, Optional[str]]]:
    """Read input from a TTY key-by-key. Returns (action, value), or None when
    stdin is not a TTY and the caller should fall back to click.prompt."""
    prompt = (
        f"Enter a URL or local file path to download '{artist} - {track}' instead "
        f"(Enter to skip, Backspace to mark as lost): "
    )
    print(prompt, end='', flush=True)

    chars: List[str] = []
    while True:
        ch = _read_key()
        if ch is None:
            return None  # not a TTY: let the caller fall back to click.prompt

        if ch in ('\r', '\n'):
            # Enter key
            print()
            if chars:
                return ('url', ''.join(chars))
            return ('skip', None)

        if ch in ('\x08', '\x7f'):
            # Backspace key
            if chars:
                chars.pop()
                print('\b \b', end='', flush=True)
                continue
            # Backspace on an empty line = mark as lost
            print()
            return ('lost', None)

        if ch == '\x03':
            # Ctrl+C — abort, skip all remaining
            print()
            return ('abort', None)

        if ch == '\x1b':
            # ESC — skip all remaining prompts
            print()
            return ('abort', None)

        # Regular character: echo and accumulate. Skip other control chars.
        if ord(ch) < 32:
            continue
        chars.append(ch)
        print(ch, end='', flush=True)


def _write_lost_song(lost_songs_path: str, row_dict: Dict[str, str]) -> None:
    """Append a song row to lost-songs.csv.

    Creates the file with a header row if it doesn't exist yet. The row data
    comes from the unmatched.csv row for this track, plus a lost_at date.

    Args:
        lost_songs_path: Path to lost-songs.csv (same directory as
            unmatched.csv).
        row_dict: Full row data from unmatched.csv for this track.
    """
    fieldnames = [
        'playlist_name', 'track_id', 'track_name', 'artist_names',
        'album_name', 'tier_tried', 'spotify_url', 'lost_at',
    ]
    row = dict(row_dict)
    row['lost_at'] = date.today().isoformat()

    file_exists = os.path.exists(lost_songs_path) and os.path.getsize(lost_songs_path) > 0

    with open(lost_songs_path, 'a', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, '') for k in fieldnames})


def _read_csv_rows(csv_path: str) -> Dict[str, Dict[str, str]]:
    """Read all rows from a CSV, keyed by spotify_url.

    Returns a dict mapping spotify_url -> full row dict. Silently returns {}
    on any read error.
    """
    rows: Dict[str, Dict[str, str]] = {}
    try:
        with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
            first_line = f.readline()
            f.seek(0)
            delimiter = ','
            for d in (',', ';', '\t', '|'):
                if d in first_line:
                    delimiter = d
                    break
            reader = csv.DictReader(f, delimiter=delimiter)
            if reader.fieldnames:
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
            for row in reader:
                url = (row.get('spotify_url') or '').strip()
                if url:
                    rows[url] = row
    except Exception:
        pass
    return rows


def _remove_from_unmatched_csv(unmatched_csv_path: str, url: str) -> None:
    """Remove all rows matching the given URL from unmatched.csv, in place.

    Uses an atomic write (write to .tmp, then os.replace) so the file is
    never left in a partial state if the process is interrupted.
    """
    if not os.path.exists(unmatched_csv_path):
        return

    rows: List[Dict[str, str]] = []
    fieldnames: Optional[List[str]] = None

    with open(unmatched_csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            if (row.get('spotify_url') or '').strip() != url:
                rows.append(row)

    if not fieldnames:
        return

    tmp = unmatched_csv_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, unmatched_csv_path)


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


def _read_lost_song_urls(lost_songs_path: str) -> set:
    """Read URLs from lost-songs.csv. Returns a set of URLs.

    lost-songs.csv lives next to unmatched.csv and is populated when the user
    presses Backspace during manual fallback to mark a track as lost. Shared by
    both the Spotify and SoundCloud download entry points so a track marked as
    lost for one service isn't re-downloaded on subsequent runs.
    """
    if not lost_songs_path or not os.path.exists(lost_songs_path):
        return set()
    urls = set()
    try:
        with open(lost_songs_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = (row.get("spotify_url") or "").strip()
                if url:
                    urls.add(url)
    except Exception as e:
        print(f"warning: failed to read lost-songs.csv {lost_songs_path}: {e}")
    return urls


def filter_manual_linked_urls(urls, library_root=None):
    """Filter out URLs that already have a valid manual link to an existing file.

    A manual link (``.manual_links.json``) means the user already pointed
    fallback at an existing crate file for this track. Re-downloading or
    re-prompting for it is pointless. The link is resolved against the crate
    root (``archive_path()``) since link paths are crate-relative.

    Returns a tuple ``(kept, skipped)`` where ``kept`` are URLs without a
    valid link and ``skipped`` are URLs whose link resolves to an existing file.
    """
    links = manual_links.load_links_safe()
    if not links:
        return list(urls), []
    root = library_root or manual_links.archive_path()
    # Load the catalog index so resolve_link can fall back to basename
    # matching when the stored path doesn't exactly match the on-disk file
    # (e.g. CJK / Hangul character differences between stored path and file).
    try:
        from lib.catalog.indexer import get_index
        catalog = get_index(root)
    except Exception:
        catalog = None
    kept = []
    skipped = []
    for url in urls:
        key = manual_links.link_key(url)
        link = links.get(key)
        if link and manual_links.resolve_link(link, root, catalog=catalog):
            skipped.append(url)
        else:
            kept.append(url)
    return kept, skipped


def apply_lost_song_filter(urls, metadata, url_file):
    """Filter out URLs previously marked as lost (via backspace in manual mode).

    lost-songs.csv lives next to unmatched.csv; URLs listed there are skipped
    so they aren't re-downloaded on subsequent runs.

    Returns (urls, metadata, url_count).
    """
    if not url_file:
        return urls, metadata, len(urls)
    lost_songs_path = os.path.join(
        os.path.dirname(os.path.abspath(url_file)), "lost-songs.csv"
    )
    lost_urls = _read_lost_song_urls(lost_songs_path)
    if not lost_urls:
        return urls, metadata, len(urls)
    lost_set = set(lost_urls)
    before = len(urls)
    urls = [u for u in urls if u not in lost_set]
    metadata = {u: m for u, m in metadata.items() if u in set(urls)}
    removed = before - len(urls)
    if removed:
        print(f"  Skipping {removed} lost song(s) (listed in lost-songs.csv).")
    return urls, metadata, len(urls)


def apply_manual_link_filter(urls, metadata):
    """Filter out URLs already covered by a manual link (.manual_links.json).

    The user already pointed fallback at an existing crate file for these
    tracks, so there's nothing to download or re-prompt for.

    Returns (urls, metadata, url_count).
    """
    if not urls:
        return urls, metadata, 0
    before = len(urls)
    urls, _ = filter_manual_linked_urls(urls, archive_path())
    metadata = {u: m for u, m in metadata.items() if u in set(urls)}
    removed = before - len(urls)
    if removed:
        print(f"  Skipping {removed} song(s) already covered by a manual link.")
    return urls, metadata, len(urls)


def process_fallback(
    batch: List[str],
    metadata: Dict[str, Dict[str, Any]],
    output_dir: str,
    format: str,
    overwrite_errors: bool,
    cookies_from_browser: Optional[str],
    resolved_ffmpeg: str,
    library_index: Optional[Dict[str, Any]] = None,
    unmatched_csv_path: Optional[str] = None,
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
        unmatched_csv_path: Optional path to the unmatched.csv being processed.
            When a track is marked as lost (backspace), its row is appended to
            lost-songs.csv (next to unmatched.csv) and removed from unmatched.csv.

    Returns:
        Tuple of (successful_urls, failed_urls, batch_succeeded_via_fallback)
    """
    print("\nInitiating fallback for batch...")
    fallback_succeeded = []
    fallback_failed = []
    fallback_skipped = []
    fallback_lost = []
    skip_all_remaining = False  # Track if user wants to skip all remaining downloads

    # Build URL -> full row mapping from unmatched.csv (for lost-songs.csv)
    rows_by_url: Dict[str, Dict[str, str]] = {}
    lost_songs_path: Optional[str] = None
    if unmatched_csv_path:
        rows_by_url = _read_csv_rows(unmatched_csv_path)
        lost_songs_path = os.path.join(
            os.path.dirname(os.path.abspath(unmatched_csv_path)), "lost-songs.csv"
        )

    for url in batch:
        fallback_succeeded, fallback_failed, fallback_skipped, fallback_lost, skip_all_remaining = _process_fallback_url(
            url, metadata, format, output_dir,
            overwrite_errors, cookies_from_browser, resolved_ffmpeg, library_index,
            rows_by_url.get(url, {}), lost_songs_path, unmatched_csv_path,
            fallback_succeeded, fallback_failed, fallback_skipped, fallback_lost, skip_all_remaining
        )

        if skip_all_remaining:
            # Mark any remaining URLs as skipped
            remaining = batch[batch.index(url) + 1:]
            for remaining_url in remaining:
                fallback_skipped.append(remaining_url)
            break

    # Determine if batch succeeded via fallback
    # No failures, no skips, and no lost marks means the batch fully succeeded
    batch_succeeded_via_fallback = (
        len(fallback_failed) == 0
        and len(fallback_skipped) == 0
        and len(fallback_lost) == 0
    )

    if fallback_failed:
        print(f"  Fallback failed for {len(fallback_failed)} URL(s) in batch.")
        # Log the failed URLs (only genuine failures, not intentional skips/lost)
        _log_urls('soft_failures.txt', fallback_failed, reason='fallback_failed')
    if fallback_lost:
        print(f"  Marked {len(fallback_lost)} URL(s) as lost (added to lost-songs.csv, removed from unmatched.csv).")
    elif fallback_skipped:
        print(f"  Skipped fallback for {len(fallback_skipped)} URL(s) in batch.")
    else:
        print("  All URLs in batch succeeded via fallback.")

    # For return value, combine failed and skipped URLs as "failed" to maintain
    # test compatibility. Lost URLs are intentional, not failures, so they are
    # not included here and are not logged to soft_failures.txt.
    total_failed = fallback_failed + fallback_skipped
    return fallback_succeeded, total_failed, batch_succeeded_via_fallback


def _process_fallback_url(url, metadata, format, output_dir,
                         overwrite_errors, cookies_from_browser, resolved_ffmpeg, library_index,
                         row_dict, lost_songs_path, unmatched_csv_path,
                         fallback_succeeded, fallback_failed, fallback_skipped, fallback_lost, skip_all_remaining):
    """Process a single URL in the fallback batch.

    Args:
        url: The URL to process
        metadata: Metadata dictionary mapping URLs to track info
        format: Audio format for downloads
        output_dir: Directory to save downloaded/copied files
        overwrite_errors: Whether to overwrite existing files
        cookies_from_browser: Browser to get cookies from
        resolved_ffmpeg: Path to ffmpeg executable
        library_index: Index of existing files (for existence check)
        row_dict: Full unmatched.csv row dict for this URL (used when marking as lost)
        lost_songs_path: Path to lost-songs.csv (None if unmatched_csv_path not provided)
        unmatched_csv_path: Path to unmatched.csv (rows are removed from here when marked lost)
        fallback_succeeded, fallback_failed, fallback_skipped, fallback_lost: Lists to update
        skip_all_remaining: Boolean tracking if user wants to skip all remaining downloads

    Returns:
        Tuple of (updated fallback_succeeded, fallback_failed, fallback_skipped,
        fallback_lost, skip_all_remaining)
    """
    meta = metadata.get(url) or {}
    artist = meta.get('artist', '')
    track = meta.get('track', '')

    # If user chose to skip all remaining, skip this URL without prompting
    if skip_all_remaining:
        print(f"  Skipping all remaining downloads (including '{artist} - {track}') due to previous skip-all.")
        fallback_skipped.append(url)
        return fallback_succeeded, fallback_failed, fallback_skipped, fallback_lost, skip_all_remaining

    # Resolve display values and predicted filename. When csv metadata is
    # missing, the URL itself is shown as the track identifier so the user
    # can still identify which track is being prompted.
    prompt_artist, prompt_track, predicted, has_meta = _resolve_fallback_display(url, metadata, format)
    stem = os.path.splitext(predicted)[0]

    # Check if already exists via pre-skip logic (if enabled and library_index provided)
    if library_index is not None and normalize_key(stem) in library_index:
        print(f"  File already exists (via pre-skip): {predicted}")
        fallback_succeeded.append(url)
        return fallback_succeeded, fallback_failed, fallback_skipped, fallback_lost, skip_all_remaining

    # Get user input for fallback source
    action, user_input = _read_fallback_input(prompt_artist, prompt_track)

    if action == 'abort':
        # Ctrl+C: skip all remaining downloads
        skip_all_remaining = True
        print("  Skipping all remaining downloads.")
        fallback_skipped.append(url)
        return fallback_succeeded, fallback_failed, fallback_skipped, fallback_lost, skip_all_remaining

    if action == 'lost':
        # Backspace: mark as lost — append to lost-songs.csv and remove from unmatched.csv
        print(f"  Marking '{prompt_artist} - {prompt_track}' as lost.")
        if lost_songs_path and row_dict:
            _write_lost_song(lost_songs_path, row_dict)
        if unmatched_csv_path:
            _remove_from_unmatched_csv(unmatched_csv_path, url)
        fallback_lost.append(url)
        return fallback_succeeded, fallback_failed, fallback_skipped, fallback_lost, skip_all_remaining

    if action == 'skip':
        print(f"  Skipping fallback for '{prompt_artist} - {prompt_track}'.")
        fallback_skipped.append(url)
        return fallback_succeeded, fallback_failed, fallback_skipped, fallback_lost, skip_all_remaining

    # action == 'url': process the user input (URL or local file)
    fallback_succeeded, fallback_failed = _process_fallback_input(
        user_input, prompt_artist, prompt_track, format, output_dir, overwrite_errors,
        cookies_from_browser, resolved_ffmpeg, fallback_succeeded, fallback_failed, url, predicted
    )

    return fallback_succeeded, fallback_failed, fallback_skipped, fallback_lost, skip_all_remaining


def _process_fallback_input(user_input, artist, track, format, output_dir,
                           overwrite_errors, cookies_from_browser, resolved_ffmpeg,
                           fallback_succeeded, fallback_failed, url, predicted):
    """Process the user input (URL or local file) for fallback.

    Args:
        user_input: User provided URL or file path
        artist: Artist name
        track: Track name
        format: Audio format for downloads
        output_dir: Directory to save downloaded/copied files
        overwrite_errors: Whether to overwrite existing files
        cookies_from_browser: Browser to get cookies from
        resolved_ffmpeg: Path to ffmpeg executable
        fallback_succeeded, fallback_failed: Lists to update
        url: Original URL being processed
        predicted: Predicted output filename

    Returns:
        Tuple of (updated fallback_succeeded, fallback_failed)
    """
    import os

    # Determine if input is a URL or file path
    if user_input.startswith(('http://', 'https://')):
        # Treat as URL, download via ytdl but use original metadata for naming
        print(f"  Downloading via ytdl from URL: {user_input}")

        ytdl_success = download_ytdl(
            user_input,
            output_dir=resolve_output_dir(output_dir),
            audio_format=format,
            audio_quality='0',
            embed_thumbnail=True,
            overwrite=overwrite_errors,
            verbose=False,
            metadata_only=False,
            cookies_from_browser=cookies_from_browser,
            ffmpeg_path=resolved_ffmpeg,
        )

        if ytdl_success:
            print("  Successfully downloaded via ytdl.")
            fallback_succeeded.append(url)
        else:
            print("  ytdl download failed.")
            fallback_failed.append(url)
    else:
        # Treat as local file path (strip the quotes Explorer's "Copy as path" adds)
        local = os.path.expanduser(user_input.strip().strip('"\''))
        if not os.path.isfile(local):
            print(f"  Local file not found: {local}")
            fallback_failed.append(url)
            return fallback_succeeded, fallback_failed

        ok = _link_or_copy_local_file(local, url, artist, track, output_dir, predicted)
        (fallback_succeeded if ok else fallback_failed).append(url)

    return fallback_succeeded, fallback_failed


def _link_or_copy_local_file(local, url, artist, track, output_dir, predicted):
    """associate a user-supplied local file with this track.

    a file already inside the crate is LINKED (lib.catalog.links) - no copy,
    so no duplicate; the matcher resolves the link as its first tier. a file
    outside the crate is new content, so it's copied in as before, and the
    copy is linked too when it landed somewhere the indexer can see.

    returns True on success.
    """
    crate = archive_path()
    try:
        rel = manual_links.add_link(url, local, artist=artist, title=track, library_root=crate)
        print(f"  Linked existing crate file: {rel}")
        return True
    except manual_links.OutsideCrate:
        pass  # new to the crate: fall through to the copy below
    except manual_links.LinksError as e:
        print(f"  Can't update the manual links file: {e}")
        return False
    except manual_links.LinkRejected as e:
        # e.g. the file sits in unorganized/ or duplicates/. copying it would
        # recreate the duplicate this feature exists to avoid.
        print(f"  Can't link {local}: {e}")
        return False

    # keep the source file's real extension: `predicted` carries the *target
    # download format* (e.g. .mp3), which would mislabel a flac/m4a/etc.
    dest = os.path.join(output_dir, os.path.splitext(predicted)[0] + os.path.splitext(local)[1])
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(local, dest)
    except Exception as e:
        print(f"  Failed to copy local file: {e}")
        return False
    print(f"  Copied local file to: {os.path.relpath(dest, output_dir)}")

    try:
        rel = manual_links.add_link(url, dest, artist=artist, title=track, library_root=crate)
        print(f"  Linked copy: {rel}")
    except manual_links.LinkRejected as e:
        # output_dir is outside the crate, or in unorganized/ (staging). not
        # an error: once it's imported, re-running fallback can link it.
        print(f"  (copy not linked yet: {e})")
    except manual_links.LinksError as e:
        print(f"  (copy not linked: {e})")
    return True
