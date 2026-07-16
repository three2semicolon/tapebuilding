
"""tapedeck/resolve - turn a (kind, spec) into crate paths to stage.

a spec is EITHER a crate-relative path/folder/file (fast, unambiguous - skips the
index entirely) OR a name (album/song title, soundtrack dir, playlist name) resolved
against the crate. resolution returns four buckets:

  folders  - crate dirs whose full subtree gets mirrored (albums, soundtracks)
  files    - individual crate audio files (songs, playlist tracks)
  m3u8     - crate .m3u8 files copied verbatim (playlists)
  warnings - unresolved specs + ambiguity notes (never fatal)

the bucket split keeps copy.py ignorant of kind: it just expands folders, copies
files + m3u8s, and writes to the same crate-relative path under the tapedeck.
"""

import os

from organize.cleanup import norm_key, EXTENSIONS
from playlists.matcher import MatchIndex, _split_artists

AUDIO_EXT = EXTENSIONS                       # .mp3 .flac .m4a .opus .ogg .wav .aac
M3U_EXT = ('.m3u8', '.m3u')


def _norm(s):
    return norm_key(s)


# --- path-or-name probe -----------------------------------------------------

def _abs(crate, spec):
    return os.path.normpath(os.path.join(crate, spec))


def as_crate_path(crate, spec, want_dir=None, want_file=None):
    """if crate/<spec> exists on disk, return its absolute path; else None.
    want_dir / want_file narrow to dir/file (both None = either)."""
    p = _abs(crate, spec)
    if want_dir and os.path.isdir(p):
        return p
    if want_file and os.path.isfile(p):
        return p
    if want_dir is None and want_file is None:
        if os.path.isdir(p) or os.path.isfile(p):
            return p
    return None


def need_index_for(kind, specs, crate):
    """does this invocation need the cached crate index (the mediafile walk)?
    path specs resolve off disk; only name specs need the index. soundtrack and
    playlist always resolve by dir/filename walk - never the index. an album name
    that matches an albums/ folder by basename also skips the index (the tag
    fallback is only needed when the folder name diverges from the tag)."""
    if kind in ('soundtrack', 'playlist'):
        return False
    if kind == 'album':
        folder_names = {_norm(os.path.basename(d)) for d in _album_folders(crate)}
        for spec in specs:
            if as_crate_path(crate, spec, want_dir=True):
                continue               # path form
            if _norm(spec) in folder_names:
                continue               # folder basename match - no index needed
            return True                 # needs the album-tag fallback
        return False
    for spec in specs:
        if not as_crate_path(crate, spec, want_file=True):
            return True                 # song-by-name needs the index
    return False


# --- directory listing helpers ---------------------------------------------

def _album_folders(crate):
    root = os.path.join(crate, 'albums')
    if not os.path.isdir(root):
        return []
    return [os.path.join(root, d) for d in os.listdir(root)
            if os.path.isdir(os.path.join(root, d))]


def _soundtrack_dirs(crate):
    """every dir under soundtracks/ except the root itself, at any depth -
    so 'sonic' (franchise) and 'sonic unleashed' (album) both match by basename."""
    root = os.path.join(crate, 'soundtracks')
    out = []
    if not os.path.isdir(root):
        return out
    for dp, dirs, _ in os.walk(root):
        if dp == root:
            continue
        for d in dirs:
            out.append(os.path.join(dp, d))
    return out


def _list_m3u8s(playlists_path):
    if not playlists_path or not os.path.isdir(playlists_path):
        return []
    out = []
    for fn in os.listdir(playlists_path):
        if os.path.splitext(fn)[1].lower() in M3U_EXT:
            out.append(os.path.join(playlists_path, fn))
    return out


def _parse_m3u8(m3u_abs):
    """(existing_files, missing_rels) from a crate .m3u8. the m3u's path lines are
    relative to its own folder (../albums/...), so resolve them against dirname."""
    existing, missing = [], []
    base = os.path.dirname(m3u_abs)
    with open(m3u_abs, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            rel = line.replace('\\', '/')
            abs_p = os.path.normpath(os.path.join(base, rel))
            if os.path.isfile(abs_p):
                existing.append(abs_p)
            else:
                missing.append(rel)
    return existing, missing


# --- per-kind resolution ---------------------------------------------------

def _resolve_album(spec, crate, index):
    warnings, folders = [], []
    p = as_crate_path(crate, spec, want_dir=True)
    if p:
        folders.append(p)
        return warnings, folders
    # name: match a folder under albums/ by basename first (no index)
    nk = _norm(spec)
    hits = [d for d in _album_folders(crate) if _norm(os.path.basename(d)) == nk]
    if hits:
        folders.extend(hits)
        if len(hits) > 1:
            warnings.append(f"album name {spec!r} matched {len(hits)} folders - loading all")
        return warnings, folders
    # fallback: album tag in the catalog (when the folder name diverges from the tag)
    if index is None:
        warnings.append(f"album {spec!r}: no folder match and no index built "
                        f"- pass the crate path (albums/...) or run with --reindex")
        return warnings, folders
    dirs = []
    for e in index:
        if _norm(e.get('album')) == nk:
            d = os.path.dirname(e.get('path') or '')
            if d:
                dirs.append(d)
    uniq = list(dict.fromkeys(dirs))
    if uniq:
        folders.extend(uniq)
        if len(uniq) > 1:
            warnings.append(f"album tag {spec!r} matched {len(uniq)} folders - loading all")
    else:
        warnings.append(f"album {spec!r}: no match (folder basename or album tag)")
    return warnings, folders


def _resolve_song(spec, crate, index, mindex):
    warnings, files = [], []
    p = as_crate_path(crate, spec, want_file=True)
    if p:
        files.append(p)
        return warnings, files
    if index is None or mindex is None:
        warnings.append(f"song {spec!r}: pass a crate file path, or run with --reindex "
                        f"to build the crate index first")
        return warnings, files
    # "Artist - Title" narrows on artist overlap; bare spec matches title only
    artist_part, title_part = '', spec
    if ' - ' in spec:
        artist_part, title_part = spec.split(' - ', 1)
    nt = _norm(title_part)
    cands = list(mindex.candidates_exact(nt))
    if artist_part:
        spot = {_norm(s) for s in _split_artists(artist_part)}
        cands = [c for c in cands if spot & c['artists']]
    if not cands:
        warnings.append(f"song {spec!r}: no title match in the index")
        return warnings, files
    paths = [c['e']['path'] for c in cands]
    for pp in paths:
        if pp and os.path.isfile(pp):
            files.append(pp)
    if len(files) > 1:
        warnings.append(f"song {spec!r}: matched {len(files)} files - loading all "
                        f"(disambiguate with a crate path)")
    return warnings, files


def _resolve_soundtrack(spec, crate):
    warnings, folders = [], []
    p = as_crate_path(crate, spec, want_dir=True)
    if p:
        folders.append(p)
        return warnings, folders
    nk = _norm(spec)
    hits = [d for d in _soundtrack_dirs(crate) if _norm(os.path.basename(d)) == nk]
    if hits:
        folders.extend(hits)
        if len(hits) > 1:
            warnings.append(f"soundtrack {spec!r} matched {len(hits)} dirs - loading all")
    else:
        warnings.append(f"soundtrack {spec!r}: no dir match under soundtracks/")
    return warnings, folders


def _resolve_playlist(spec, crate, playlists_path):
    warnings, files, m3u8 = [], [], []
    if not playlists_path:
        warnings.append(f"playlist {spec!r}: PLAYLISTS_PATH not set - pass it via "
                        f"--playlists-path or .env")
        return warnings, files, m3u8
    # path form: a crate .m3u8 path or a bare filename under playlists/
    p = as_crate_path(crate, spec, want_file=True)
    if p and os.path.splitext(p)[1].lower() in M3U_EXT:
        m3u8_path = p
    elif os.path.isfile(_abs(playlists_path, spec)) \
            and os.path.splitext(spec)[1].lower() in M3U_EXT:
        m3u8_path = _abs(playlists_path, spec)
    else:
        m3u8_path = None
    if not m3u8_path:
        nk = _norm(spec)
        hits = [m for m in _list_m3u8s(playlists_path)
                if _norm(os.path.splitext(os.path.basename(m))[0]) == nk]
        if not hits:
            warnings.append(f"playlist {spec!r}: no .m3u8 match in {playlists_path}")
            return warnings, files, m3u8
        if len(hits) > 1:
            warnings.append(f"playlist {spec!r} matched {len(hits)} files - loading all")
        for m in hits:
            _add_playlist(m, warnings, files, m3u8)
        return warnings, files, m3u8
    _add_playlist(m3u8_path, warnings, files, m3u8)
    return warnings, files, m3u8


def _add_playlist(m3u8_path, warnings, files, m3u8):
    m3u8.append(m3u8_path)
    existing, missing = _parse_m3u8(m3u8_path)
    files.extend(existing)
    if missing:
        warnings.append(f"{os.path.basename(m3u8_path)}: {len(missing)} track(s) "
                        f"not in crate (skipped): {missing[0]}{', ...' if len(missing) > 1 else ''}")


# --- aggregate --------------------------------------------------------------

def resolve_targets(kind, specs, crate, playlists_path=None, index=None, mindex=None,
                    verbose=False):
    """resolve every spec -> {folders, files, m3u8, warnings}. index/mindex are
    only needed for album-by-tag fallback and song-by-name; pass None for the
    path-only kinds."""
    warnings, folders, files, m3u8 = [], [], [], []
    for spec in specs:
        if kind == 'album':
            w, f = _resolve_album(spec, crate, index)
            warnings += w; folders += f
        elif kind == 'song':
            w, f = _resolve_song(spec, crate, index, mindex)
            warnings += w; files += f
        elif kind == 'soundtrack':
            w, f = _resolve_soundtrack(spec, crate)
            warnings += w; folders += f
        elif kind == 'playlist':
            w, f, m = _resolve_playlist(spec, crate, playlists_path)
            warnings += w; files += f; m3u8 += m
        else:
            warnings.append(f"unknown kind {kind!r}")
    # de-dup preserving order (folders handled as set-of-contents in copy.py)
    folders = list(dict.fromkeys(folders))
    files = list(dict.fromkeys(files))
    m3u8 = list(dict.fromkeys(m3u8))
    return {'folders': folders, 'files': files, 'm3u8': m3u8, 'warnings': warnings}
