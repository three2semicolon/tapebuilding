
"""playlists - build/maintain local .m3u8 files from spotify playlists.

for each spotify playlist (default: only the ones you own), resolve every track
to a file in the crate and write one .m3u8 (relative paths, with a #SPOTIFY:<id>
comment per entry) into PLAYLISTS_PATH. unresolved tracks are logged to the
exports dir as a handoff for the existing `spotify` downloader.

re-running is the add/remove/update semantic: the .m3u8 is rebuilt from current
spotify membership, so adds/removes/reorders on spotify flow through on the next
run. songs may be in multiple playlists.

usage:
  uv run playlists --playlist "_obs"                 # preview one (no files written)
  uv run playlists --apply --playlist "_obs"         # write it
  uv run playlists --apply --rescrape --playlist "_obs"  # rescrape just _obs, then build it
  uv run playlists --apply                            # build all your own playlists
  uv run playlists --apply --all                     # include followed/shared lists
  uv run playlists --apply --rescrape --covers        # refresh from spotify + art
  uv run playlists --reindex                          # rebuild the local index sidecar
"""

import argparse
import csv
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from download.spotify_utils import authenticate_spotify, get_playlist_tracks
from download.spotify_to_csv import export_all_data, extract_playlist_id_from_url

from .indexer import (
    resolve_playlists_path, resolve_archive_path, resolve_exports_dir, get_index,
)
from .matcher import MatchIndex, match_rows
from .m3u import safe_name, write_m3u8

try:
    sys.stdout.reconfigure(encoding='utf-8')  # non-ascii artist names on windows
except Exception:
    pass


PLAYLIST_TRACKS_FIELDS = (
    'playlist_id', 'playlist_name', 'track_id', 'track_name', 'artist_names',
    'album_name', 'duration_ms', 'explicit', 'popularity', 'added_at',
    'added_by', 'spotify_url', 'track_number', 'disc_number', 'is_local',
)

PLAYLIST_META_FIELDS = (
    'id', 'name', 'description', 'owner', 'public', 'track_count', 'playlist_url',
)


def _read_csv(path):
    """read a csv into a list of dicts, or [] if missing."""
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def _write_csv(path, rows, fields):
    """atomic, non-fatal csv write. mirrors _write_unmatched: a locked target
    (editor/scanner holding it) warns rather than aborting the build."""
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, path)
    except OSError as e:
        print(f"  warning: could not write {path}: {e}")


def _group_tracks_by_playlist(rows):
    """playlist_tracks.csv long form -> {playlist_id: [rows...]} preserving csv order
    (which is spotify's playlist order)."""
    groups = {}
    order = []
    for r in rows:
        pid = r.get('playlist_id')
        if not pid:
            continue
        if pid not in groups:
            groups[pid] = []
            order.append(pid)
        groups[pid].append(r)
    return groups


def _select_playlists(playlists_csv, args):
    """apply scope (--name over --all over --mine) -> [(meta_row), ...]."""
    rows = _read_csv(playlists_csv)
    if not rows:
        raise ValueError(f"no playlists.csv found at {playlists_csv} - run `export` or --rescrape first")

    if args.names:
        wanted = []
        for token in args.names:
            as_id = extract_playlist_id_from_url(token)
            is_id = len(as_id) >= 16          # bare id, or id extracted from a url
            wanted.append((token, as_id, is_id))
        selected = []
        for meta in rows:
            for token, as_id, is_id in wanted:
                if is_id and meta.get('id') == as_id:
                    selected.append(meta); break
                if not is_id and meta.get('name') == token:
                    selected.append(meta); break
        return selected

    if args.all:
        return rows

    # --mine (default)
    user_id = os.getenv('SPOTIFY_USER_ID') or os.getenv('spotify_user_id')
    if not user_id:
        print("warning: SPOTIFY_USER_ID not set - can't filter to your playlists; building all.")
        return rows
    return [r for r in rows if (r.get('owner') or '') == user_id]


def _read_existing_index(args, exports_dir):
    library = resolve_archive_path(args.archive_path)
    if not os.path.isdir(library):
        raise ValueError(f"library root not found: {library} (ARCHIVE_PATH / --archive-path)")
    return get_index(library, exports_dir, reindex=args.reindex, verbose=args.verbose)


def _download_cover(sp, playlist_id, dest_path):
    import requests
    try:
        data = sp.playlist(playlist_id, fields='images')
    except Exception as e:
        print(f"  warning: could not fetch cover for {playlist_id}: {e}")
        return False
    images = data.get('images') or []
    url = None
    if images:
        url = max(images, key=lambda im: im.get('width') or 0).get('url')
    if not url:
        return False
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    tmp = dest_path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(resp.content)
    os.replace(tmp, dest_path)
    return True


def _scope_rescrape(sp, args, exports_dir):
    """--rescrape with -p: fetch only the named playlist(s) from spotify and
    patch their rows into playlists.csv + playlist_tracks.csv, instead of the
    full export_all_data walk of every owned playlist. a name token resolves to
    an id via the existing playlists.csv (one we don't already know can't be
    scraped by name - pass its url or id, or run a full --rescrape first to
    learn it); a url or bare id fetches directly."""
    playlists_csv = os.path.join(exports_dir, 'playlists.csv')
    tracks_csv = os.path.join(exports_dir, 'playlist_tracks.csv')
    metas = _read_csv(playlists_csv)          # [] on a first run
    tracks = _read_csv(tracks_csv)
    name_to_id = {m.get('name'): m.get('id') for m in metas if m.get('name') and m.get('id')}

    to_fetch, missing = [], []
    for token in args.names:
        as_id = extract_playlist_id_from_url(token)
        if len(as_id) >= 16:                         # bare id, or id extracted from a url
            to_fetch.append((token, as_id))
        elif token in name_to_id:                    # a name we already know
            to_fetch.append((token, name_to_id[token]))
        else:
            missing.append(token)

    if missing:
        print(f"warning: can't rescrape by name (not in playlists.csv): {', '.join(missing)}")
        print("         pass its url or id instead, or run a full --rescrape first to learn it.")
    if not to_fetch:
        return

    print(f"rescraping {len(to_fetch)} playlist(s) (--rescrape -p) into {exports_dir}")
    fetch_ids = {pid for _, pid in to_fetch}
    out_tracks = [r for r in tracks if r.get('playlist_id') not in fetch_ids]

    for token, pid in to_fetch:
        try:
            pl = sp.playlist(pid)
        except Exception as e:
            print(f"  warning: could not fetch playlist {token}: {e}")
            continue
        name = pl.get('name') or token
        meta = {
            'id': pl.get('id', ''),
            'name': name,
            'description': pl.get('description', '') or '',
            'owner': (pl.get('owner') or {}).get('display_name', '') or '',
            'public': pl.get('public', False),
            'track_count': (pl.get('tracks') or {}).get('total', 0),
            'playlist_url': (pl.get('external_urls') or {}).get('spotify', ''),
        }
        # replace in place to keep playlists.csv row order; else append
        for i, m in enumerate(metas):
            if m.get('id') == pid:
                metas[i] = meta
                break
        else:
            metas.append(meta)

        new_tracks = get_playlist_tracks(sp, pid, name)
        print(f"  - {name}: {len(new_tracks)} tracks")
        out_tracks.extend(new_tracks)

    _write_csv(playlists_csv, metas, PLAYLIST_META_FIELDS)
    _write_csv(tracks_csv, out_tracks, PLAYLIST_TRACKS_FIELDS)


def build_playlists(args):
    playlists_path = resolve_playlists_path(args.playlists_path)
    exports_dir = resolve_exports_dir(playlists_path, args.exports_dir)
    os.makedirs(playlists_path, exist_ok=True)

    sp = None
    if args.rescrape or args.covers:
        sp = authenticate_spotify()
    if args.rescrape:
        if args.names:
            _scope_rescrape(sp, args, exports_dir)
        else:
            print("rescraping spotify (--rescrape) into " + exports_dir)
            export_all_data(sp, exports_dir, my_playlists_only=True)

    playlists_csv = os.path.join(exports_dir, 'playlists.csv')
    tracks_csv = os.path.join(exports_dir, 'playlist_tracks.csv')
    selected = _select_playlists(playlists_csv, args)
    grouped = _group_tracks_by_playlist(_read_csv(tracks_csv))

    print(f"\nbuilding {len(selected)} playlist(s) from {tracks_csv}")
    if len(selected) <= 12 or args.verbose:
        for m in selected:
            print(f"  - {m.get('name')} ({m.get('track_count')} tracks on spotify)")

    index = _read_existing_index(args, exports_dir)
    mindex = MatchIndex(index)

    total_tracks = total_matched = total_unmatched = total_written = 0
    unmatched_rows = []

    for i, meta in enumerate(selected, 1):
        pid = meta.get('id')
        name = meta.get('name') or meta.get('id') or 'Unknown'
        rows = grouped.get(pid, [])
        results = match_rows(rows, mindex, verbose=args.verbose)

        matched_entries = []
        for rec in results:
            total_tracks += 1
            row = rec['row']
            if rec['path']:
                total_matched += 1
                matched_entries.append({
                    'track_id': row.get('track_id', ''),
                    'artist': row.get('artist_names', ''),
                    'title': row.get('track_name', ''),
                    'length': rec['length'],
                    'path': rec['path'],
                })
            else:
                total_unmatched += 1
                unmatched_rows.append({
                    'playlist_name': name,
                    'track_id': row.get('track_id', ''),
                    'track_name': row.get('track_name', ''),
                    'artist_names': row.get('artist_names', ''),
                    'album_name': row.get('album_name', ''),
                    'tier_tried': rec['tier'],
                    'spotify_url': row.get('spotify_url', ''),
                })

        unmatched_count = len(rows) - len(matched_entries)
        print(f"\n[{i}/{len(selected)}] {name} - {len(matched_entries)}/{len(rows)} matched ({unmatched_count} unmatched)")

        if args.apply and matched_entries:
            m3u8_path = os.path.join(playlists_path, safe_name(name) + '.m3u8')
            write_m3u8(m3u8_path, matched_entries)
            total_written += 1
            print(f"  wrote {m3u8_path}")
            if args.covers:
                cover = os.path.join(playlists_path, safe_name(name) + '.jpg')
                got = _download_cover(sp, pid, cover)
                if got:
                    print(f"  wrote {cover}")

    _write_unmatched(exports_dir, unmatched_rows)

    print(f"\ndone. {total_written}/{len(selected)} playlists written "
          f"({total_matched} matched / {total_unmatched} unmatched of {total_tracks} tracks)")
    print(f"unmatched -> {os.path.join(exports_dir, 'unmatched.csv')}, "
          f"{os.path.join(exports_dir, 'unmatched_urls.txt')}")


def _write_unmatched(exports_dir, rows):
    """atomic, non-fatal: the handoff is a convenience sidecar, so a locked target
    (file open in an editor, a scanner holding it) should warn, not abort the build."""
    csv_path = os.path.join(exports_dir, 'unmatched.csv')
    txt_path = os.path.join(exports_dir, 'unmatched_urls.txt')
    fields = ('playlist_name', 'track_id', 'track_name', 'artist_names',
              'album_name', 'tier_tried', 'spotify_url')
    urls = []
    seen = set()
    body_lines = []
    body_lines.append(','.join(fields))
    for r in rows:
        body_lines.append(','.join(_csv_escape(r.get(k, '')) for k in fields))
        u = (r.get('spotify_url') or '').strip()
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    for path, text in ((csv_path, '\n'.join(body_lines) + '\n'),
                        (txt_path, '\n'.join(urls) + ('\n' if urls else ''))):
        try:
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8', newline='') as f:
                f.write(text)
            os.replace(tmp, path)
        except OSError as e:
            print(f"  warning: could not write {path}: {e}")
    return len(rows)


def _csv_escape(v):
    v = str(v)
    if ',' in v or '"' in v or '\n' in v:
        v = '"' + v.replace('"', '""') + '"'
    return v


def main():
    p = argparse.ArgumentParser(description='build local .m3u8 playlists from spotify playlists',
                                allow_abbrev=False)
    p.add_argument('--apply', action='store_true',
                   help='write the .m3u8 files (default is a preview)')
    scope = p.add_mutually_exclusive_group()
    scope.add_argument('--all', action='store_true',
                       help='build every playlist in playlists.csv (incl. followed/shared)')
    scope.add_argument('--mine', action='store_true', help='only your own playlists (default)')
    p.add_argument('-p', '--playlist', action='append', dest='names', metavar='NAME|ID', default=[],
                   help='build a specific playlist by name or spotify id (repeatable; overrides scope)')
    p.add_argument('--rescrape', action='store_true',
                   help="refresh the spotify csvs first (full export; with -p, only the named playlists)")
    p.add_argument('--covers', action='store_true',
                   help='download each playlist cover to <name>.jpg (needs --rescrape or spotify auth)')
    p.add_argument('--reindex', action='store_true',
                   help='rebuild the local .playlist_index.jsonl sidecar before matching')
    p.add_argument('--verbose', action='store_true', help='print every match decision')
    p.add_argument('-o', '--playlists-path', help='PLAYLISTS_PATH override')
    p.add_argument('--archive-path', help='ARCHIVE_PATH (crate root) override')
    p.add_argument('--exports-dir', help='exports dir override (default PLAYLISTS_PATH/exports)')
    args = p.parse_args()

    try:
        build_playlists(args)
    except Exception as e:
        print(f"error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
