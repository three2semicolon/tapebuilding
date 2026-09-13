"""playlists.build - build/maintain local .m3u8 files from spotify playlists.

for each spotify playlist (default: only the ones you own), resolve every track
to a file in the crate and write one .m3u8 (relative paths, with a #SPOTIFY:<id>
comment per entry) into PLAYLISTS_PATH. unresolved tracks are logged to the
exports dir as a handoff for the existing `spotify` downloader.

re-running is the add/remove/update semantic: the .m3u8 is rebuilt from current
spotify membership, so adds/removes/reorders on spotify flow through on the next
run. songs may be in multiple playlists.

cli.py owns argument parsing / exit codes; build_playlists() below is the
plain, import-safe entry point - no argparse/sys.exit in here, so core/ can
call it directly later without shelling out.

usage (via playlists' cli):
  uv run playlists --playlist "_obs"                 # preview one (no files written)
  uv run playlists --apply --playlist "_obs"         # write it
  uv run playlists --apply --rescrape --playlist "_obs"  # rescrape just _obs, then build it
  uv run playlists --apply                            # build all your own playlists
  uv run playlists --apply --all                     # include followed/shared lists
  uv run playlists --apply --rescrape --covers        # refresh from spotify + art
  uv run playlists --reindex                          # rebuild the local index sidecar

lib/ refactor: indexer/matcher/m3u now come from lib.catalog.indexer,
lib.catalog.matcher, lib.m3u instead of the (now-deleted) playlists.indexer/
playlists.matcher/playlists.m3u; root resolution comes from lib.paths
instead of playlists.indexer's own resolvers. download.spotify_utils /
download.spotify_to_csv are gone post-Phase-3 - auth is
lib.spotify_auth.authenticate_user(), and get_playlist_tracks/
export_all_data/extract_playlist_id_from_url now live in
download.spotify_api / download.spotify_export respectively.
"""

import csv
import os
import sys

from lib.spotify_auth import authenticate_user
from download.spotify_api import get_playlist_tracks
from download.spotify_export import export_all_data, extract_playlist_id_from_url

from lib.paths import (
    archive_path as resolve_archive_path,
    playlists_path as resolve_playlists_path,
    exports_dir as resolve_exports_dir,
)
from lib.catalog.indexer import get_index
from lib.catalog.matcher import MatchIndex, match_rows
from lib.m3u import safe_name, write_m3u8

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
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def _write_csv(path, rows, fields):
    """atomic, non-fatal csv write. mirrors _write_unmatched: a locked target
    (editor/scanner holding it) warns rather than aborting the build."""
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8-sig', newline='') as f:
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


def _select_playlists(playlists_csv, names, all_playlists):
    """apply scope (names over all_playlists over the 'mine' default) ->
    [(meta_row), ...]. unchanged from the pre-lib/ version - just takes the
    two scope values directly instead of an argparse Namespace."""
    rows = _read_csv(playlists_csv)
    if not rows:
        raise ValueError(f"no playlists.csv found at {playlists_csv} - run `export` or --rescrape first")

    if names:
        wanted = []
        for token in names:
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

    if all_playlists:
        return rows

    # default: only your own playlists
    user_id = os.getenv('SPOTIFY_USER_ID')
    if not user_id:
        print("warning: SPOTIFY_USER_ID not set - can't filter to your playlists; building all.")
        return rows
    return [r for r in rows if (r.get('owner') or '') == user_id]


def _read_existing_index(archive_path, exports_dir, reindex, verbose):
    library = resolve_archive_path(archive_path)
    if not os.path.isdir(library):
        raise ValueError(f"library root not found: {library} (ARCHIVE_PATH / --archive-path)")
    return get_index(library, exports_dir, reindex=reindex, verbose=verbose)


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


def _scope_rescrape(sp, names, exports_dir):
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
    for token in names:
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


def build_playlists(apply=False, all_playlists=False, names=None, rescrape=False,
                     covers=False, reindex=False, verbose=False,
                     playlists_path=None, archive_path=None, exports_dir=None):
    """build/refresh local .m3u8s from current spotify playlist membership.

    plain, import-safe entry point - cli.py resolves click options into
    these kwargs and turns exceptions into exit codes; nothing in here
    calls sys.exit(), so core/ can call this directly later. `mine` isn't
    a parameter here on purpose: it was always a no-op in the original too
    (argparse only used it for the --all/--mine mutual-exclusion error,
    never inspected past that) - that check now lives in cli.py.
    """
    names = names or []
    playlists_path_resolved = resolve_playlists_path(playlists_path)
    exports_dir_resolved = resolve_exports_dir(playlists_path_resolved, exports_dir)
    os.makedirs(playlists_path_resolved, exist_ok=True)

    sp = None
    if rescrape or covers:
        sp = authenticate_user()
    if rescrape:
        if names:
            _scope_rescrape(sp, names, exports_dir_resolved)
        else:
            print("rescraping spotify (--rescrape) into " + exports_dir_resolved)
            export_all_data(sp, exports_dir_resolved, my_playlists_only=True)

    playlists_csv = os.path.join(exports_dir_resolved, 'playlists.csv')
    tracks_csv = os.path.join(exports_dir_resolved, 'playlist_tracks.csv')
    selected = _select_playlists(playlists_csv, names, all_playlists)
    grouped = _group_tracks_by_playlist(_read_csv(tracks_csv))

    print(f"\nbuilding {len(selected)} playlist(s) from {tracks_csv}")
    if len(selected) <= 12 or verbose:
        for m in selected:
            print(f"  - {m.get('name')} ({m.get('track_count')} tracks on spotify)")

    index = _read_existing_index(archive_path, exports_dir_resolved, reindex, verbose)
    mindex = MatchIndex(index)

    total_tracks = total_matched = total_unmatched = total_written = 0
    unmatched_rows = []

    for i, meta in enumerate(selected, 1):
        pid = meta.get('id')
        name = meta.get('name') or meta.get('id') or 'Unknown'
        rows = grouped.get(pid, [])
        results = match_rows(rows, index=mindex, verbose=verbose)

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

        if apply and matched_entries:
            m3u8_path = os.path.join(playlists_path_resolved, safe_name(name) + '.m3u8')
            write_m3u8(m3u8_path, matched_entries)
            total_written += 1
            print(f"  wrote {m3u8_path}")
            if covers:
                cover = os.path.join(playlists_path_resolved, safe_name(name) + '.jpg')
                got = _download_cover(sp, pid, cover)
                if got:
                    print(f"  wrote {cover}")

    _write_unmatched(exports_dir_resolved, unmatched_rows)

    print(f"\ndone. {total_written}/{len(selected)} playlists written "
          f"({total_matched} matched / {total_unmatched} unmatched of {total_tracks} tracks)")
    print(f"unmatched -> {os.path.join(exports_dir_resolved, 'unmatched.csv')}, "
          f"{os.path.join(exports_dir_resolved, 'unmatched_urls.txt')}")
    return True


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
            with open(tmp, 'w', encoding='utf-8-sig', newline='') as f:
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
