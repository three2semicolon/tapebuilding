"""app.routers.playlists - playlist CRUD, cover art, membership lookup, ops,
detach/reattach, refresh/rebuild, undo, relink, etag, links.

Playlist files live in ``PLAYLISTS_PATH`` and entries are relative to the
playlist's own folder.  Every mutating endpoint snapshots the file first so
``POST /api/playlists/{name}/undo`` can restore it; synced playlists get
``#TAPEDECK-EDITED:1`` when the app mutates them, and entries added to a
synced playlist are marked ``#TAPEDECK-LOCAL``.
"""

import csv
import os
import threading
import time
from collections import deque
from urllib.parse import quote

from fastapi import APIRouter, Body, Header, UploadFile, File
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lib.m3u import (
    read_entries,
    read_m3u8,
    read_source,
    write_m3u8,
)
from lib.paths import (
    archive_path,
    crate_root,
    exports_dir,
    path_key,
    playlists_path,
    to_rel,
)
from lib.tags import read_tags
from lib.catalog.indexer import get_index
from lib.catalog.match_index import MatchIndex
from lib.catalog.links import (
    LinkRejected,
    LinksError,
    add_link as _add_link,
    _build_by_base_index,
    _classify_link,
)
from playlists.build import build_playlists, plan_playlist

from app.services.guard import confine, resolve_in
from app.services.library_index import LibraryIndex
from app.services.membership import build_index as _build_membership, invalidate_index

router = APIRouter()

_lib_index = LibraryIndex()

# ------------------------------------------------------------------ state

_PL_LOCKS = {}  # name -> threading.RLock
_PL_SNAPS = {}  # name -> deque of snapshot dicts, maxlen ~20
_PL_STATE_LOCK = threading.Lock()  # guards _PL_LOCKS / _PL_SNAPS dicts
MAX_SNAPSHOTS = 20
HISTORY_DIR = ".history"


def _pl_lock(name):
    with _PL_STATE_LOCK:
        lock = _PL_LOCKS.get(name)
        if lock is None:
            lock = _PL_LOCKS[name] = threading.RLock()
        return lock


def _pl_snaps(name):
    with _PL_STATE_LOCK:
        snaps = _PL_SNAPS.get(name)
        if snaps is None:
            snaps = _PL_SNAPS[name] = deque(maxlen=MAX_SNAPSHOTS)
        return snaps


def _snapshot(name, op_type="ops"):
    """Save the current playlist file text + headers for undo."""
    pl_dir = playlists_path()
    path = confine(pl_dir, name)
    if path is None or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    snap = {
        "type": op_type,
        "name": name,
        "text": text,
        "source": read_source(path),
        "path": path,
    }
    _pl_snaps(name).append(snap)
    return snap


def _restore_text(path, text):
    """Write raw text to a playlist file atomically."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def _etag(path):
    """etag = mtime_ns + size; None when the file doesn't exist."""
    try:
        st = os.stat(path)
        return f"{st.st_mtime_ns}_{st.st_size}"
    except OSError:
        return None


def _read_detached(path):
    """Read the #TAPEDECK-DETACHED:<service>:<id> header value, or None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 8:
                    break
                line = line.strip()
                if line.startswith("#TAPEDECK-DETACHED:"):
                    return line[len("#TAPEDECK-DETACHED:") :].strip()
    except OSError:
        pass
    return None


def _playlist_cover_file(pl_dir, name):
    """return the cover image next to a playlist, or None."""
    stem = name.removesuffix(".m3u8").removesuffix(".m3u")
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        cand = os.path.join(pl_dir, stem + ext)
        if os.path.isfile(cand):
            return cand
    return None


def _playlist_cover_url(pl_dir, name):
    f = _playlist_cover_file(pl_dir, name)
    return f"/api/playlists/{quote(name)}/cover" if f is not None else None


def _playlist_meta(pl_dir, name):
    """{name, path, kind, source_id, cover, count, duration, edited,
    last_synced} for one playlist file."""
    path = os.path.join(pl_dir, name)
    if not os.path.isfile(path):
        return None
    entries, source, edited = read_entries(path)
    detached = _read_detached(path)

    kind = "local"
    source_id = None
    if detached:
        kind = "detached"
        source_id = detached
    elif source:
        if source.startswith("spotify:") or source.startswith("soundcloud:"):
            kind = "synced"
            source_id = source

    count = len(entries)
    duration = round(sum(float(e.get("length") or 0) for e in entries), 1)
    cover = _playlist_cover_url(pl_dir, name)
    st = os.stat(path)

    return {
        "name": name,
        "path": path,
        "kind": kind,
        "source_id": source_id,
        "cover": cover,
        "count": count,
        "duration": duration,
        "edited": edited,
        "last_synced": st.st_mtime,
    }


def _ensure_index_loaded():
    """Load the shared crate index if it's idle, so playlist entries can be
    joined with file metadata."""
    if _lib_index.status()["state"] == "idle":
        _lib_index.load()


def _entry_with_index(entry):
    """Join a read_entries() entry with crate-index metadata, falling back to
    the #EXTINF data when the file isn't in the index."""
    result = {
        "track_id": entry.get("track_id") or "",
        "artist": entry.get("artist") or "",
        "title": entry.get("title") or "",
        "album": entry.get("album") or "",
        "length": float(entry.get("length") or 0),
        "path": entry.get("path"),
        "rel": entry.get("rel") or "",
        "exists": entry.get("exists", False),
        "local": bool(entry.get("local")),
        "extinf": entry.get("extinf"),
    }
    p = entry.get("path")
    if p:
        idx = _lib_index.by_path(p)
        if idx:
            result["artist"] = idx.get("artist") or result["artist"]
            result["title"] = idx.get("title") or result["title"]
            result["album"] = idx.get("album") or result["album"]
            result["length"] = float(idx.get("length") or result["length"])
            result["track"] = idx.get("track", 0)
            result["disc"] = idx.get("disc", 0)
            result["year"] = idx.get("year", 0)
    return result


# ---------------------------------------------------------------- listing


@router.get("/api/playlists")
def list_playlists():
    pl_dir = playlists_path()
    entries = []
    if os.path.isdir(pl_dir):
        for name in sorted(os.listdir(pl_dir)):
            if not name.lower().endswith((".m3u", ".m3u8")):
                continue
            meta = _playlist_meta(pl_dir, name)
            if meta is not None:
                entries.append(meta)
    return {"playlists": entries}


@router.get("/api/playlists/{name}/cover")
def playlist_cover(name: str):
    """serve the cover image sitting next to a playlist file, if any."""
    pl_dir = playlists_path()
    candidate = confine(pl_dir, name)
    if candidate is None:
        return Response(status_code=204)
    f = _playlist_cover_file(pl_dir, os.path.basename(candidate))
    if f is None:
        return Response(status_code=204)
    ext = os.path.splitext(f)[1].lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")
    return Response(content=open(f, "rb").read(), media_type=media_type)


@router.post("/api/playlists/{name}/cover")
def upload_playlist_cover(name: str, file: UploadFile = File(...)):
    """upload a cover image for a playlist, saved next to the playlist file."""
    pl_dir = playlists_path()
    candidate = confine(pl_dir, name)
    if candidate is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    pl_path = os.path.basename(candidate)
    stem = pl_path.removesuffix(".m3u8").removesuffix(".m3u")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if not ext:
        ext = ".jpg"

    cover_path = os.path.join(pl_dir, stem + ext)
    content = file.file.read()
    with open(cover_path, "wb") as f:
        f.write(content)

    return {"ok": True, "cover": f"/api/playlists/{quote(name)}/cover"}


# ---------------------------------------------------------------- membership


@router.get("/api/tracks/{path:path}/playlists")
def track_playlists(path: str):
    """which playlists a single track already lives in."""
    return {"playlists": _membership_build().get(path_key(path), [])}


@router.post("/api/tracks/playlists")
def tracks_playlists(body: dict = Body(...)):
    """which playlists each of the given absolute track paths lives in."""
    paths = body.get("paths") or []
    if not isinstance(paths, list):
        return JSONResponse({"error": "paths must be a list of track paths"}, status_code=400)
    index = _membership_build()
    return {"playlists": {p: index.get(path_key(p), []) for p in paths}}


def _membership_build():
    return _build_membership()


# ---------------------------------------------------------------- legacy read


@router.get("/api/playlist")
def get_playlist(path: str):
    return read_m3u8(path)


# ---------------------------------------------------------------- create


class PlaylistCreate(BaseModel):
    path: str
    entries: list = []


@router.post("/api/playlists")
def create_playlist(pl: PlaylistCreate):
    pl_dir = playlists_path()
    path = pl.path if os.path.isabs(pl.path) else os.path.join(pl_dir, pl.path)
    # app-owned playlists are always local and always stamped
    write_m3u8(path, pl.entries, source="local")
    invalidate_index()
    return {"ok": True}


# ---------------------------------------------------------------- rename


@router.patch("/api/playlists/{name}")
def rename_playlist(name: str, body: dict):
    pl_dir = playlists_path()
    src = confine(pl_dir, name)
    if src is None or not os.path.isfile(src):
        return JSONResponse({"error": "not found"}, status_code=404)
    new_name = (body or {}).get("new_name", "")
    if not new_name or "/" in new_name or "\\" in new_name or new_name in (".", ".."):
        return JSONResponse({"error": "invalid name"}, status_code=400)
    dst = confine(pl_dir, new_name)
    if dst is None:
        return JSONResponse({"error": "invalid name"}, status_code=400)
    if os.path.exists(dst):
        return JSONResponse({"error": "playlist already exists"}, status_code=409)

    # snapshot before mutating, for undo
    _snapshot(name, op_type="rename")

    os.rename(src, dst)
    # move the cover image along with it
    cover = _playlist_cover_file(pl_dir, name)
    if cover is not None:
        stem = new_name.removesuffix(".m3u8").removesuffix(".m3u")
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            if cover.endswith(ext):
                dst_cover = os.path.join(pl_dir, stem + ext)
                os.rename(cover, dst_cover)
                break
    invalidate_index()
    return {"ok": True, "name": new_name}


# ---------------------------------------------------------------- delete


@router.delete("/api/playlists/{name}")
def delete_playlist(name: str):
    pl_dir = playlists_path()
    path = confine(pl_dir, name)
    if path is None or not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)

    # snapshot before mutating, for undo
    _snapshot(name, op_type="delete")

    # move to .history instead of outright deletion
    hdir = os.path.join(pl_dir, HISTORY_DIR)
    os.makedirs(hdir, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    hist_name = f"{ts}_{name}"
    hist_path = os.path.join(hdir, hist_name)
    os.rename(path, hist_path)
    # move the cover along
    cover = _playlist_cover_file(pl_dir, name)
    if cover is not None:
        stem = name.removesuffix(".m3u8").removesuffix(".m3u")
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            if cover.endswith(ext):
                os.rename(cover, os.path.join(hdir, f"{ts}_{stem}{ext}"))
                break
    invalidate_index()
    return {"ok": True, "history": hist_name}


# ---------------------------------------------------------------- undo


@router.post("/api/playlists/{name}/undo")
def undo_playlist(name: str):
    """Restore the last snapshot for this playlist."""
    snaps = _pl_snaps(name)
    if not snaps:
        return JSONResponse({"error": "nothing to undo"}, status_code=409)
    snap = snaps.pop()
    path = snap["path"]
    _restore_text(path, snap["text"])
    # if this was a delete, clean up the .history copy
    if snap["type"] == "delete":
        hdir = os.path.join(playlists_path(), HISTORY_DIR)
        if os.path.isdir(hdir):
            for fn in os.listdir(hdir):
                if fn.endswith("_" + snap["name"]):
                    try:
                        os.remove(os.path.join(hdir, fn))
                    except OSError:
                        pass
                    break
    invalidate_index()
    return {"ok": True, "name": snap["name"]}


# ---------------------------------------------------------------- full playlist read


@router.get("/api/playlists/{name}")
def get_playlist_full(name: str, if_match: str | None = Header(default=None, alias="If-Match")):
    """Return the full playlist: entries joined with index metadata, ghosts,
    etag, duration.  ``If-Match`` is checked against the current etag; a
    mismatch returns 409 so a stale client never clobbers a concurrent write."""
    pl_dir = playlists_path()
    path = confine(pl_dir, name)
    if path is None or not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)

    current_etag = _etag(path)
    if if_match is not None and if_match != current_etag:
        return JSONResponse({"error": "etag mismatch"}, status_code=409)

    _ensure_index_loaded()

    entries_raw, source, edited = read_entries(path)
    detached = _read_detached(path)

    kind = "local"
    source_id = None
    if detached:
        kind = "detached"
        source_id = detached
    elif source:
        if source.startswith("spotify:") or source.startswith("soundcloud:"):
            kind = "synced"
            source_id = source

    cover = _playlist_cover_url(pl_dir, name)

    entries = []
    ghosts = []
    duration = 0.0
    for i, e in enumerate(entries_raw):
        entry = _entry_with_index(e)
        entry["id"] = i
        duration += entry["length"]
        if e.get("exists"):
            entries.append(entry)
        else:
            ghosts.append(entry)

    return {
        "name": name,
        "kind": kind,
        "source_id": source_id,
        "cover": cover,
        "etag": current_etag,
        "edited": edited,
        "entries": entries,
        "ghosts": ghosts,
        "duration": round(duration, 1),
    }


# ---------------------------------------------------------------- update tracks (legacy)


@router.post("/api/playlists/{name}/tracks")
def update_playlist_tracks(name: str, entries: list = Body(...)):
    pl_dir = playlists_path()
    path = confine(pl_dir, name)
    if path is None or not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    source = read_source(path)
    write_m3u8(path, entries, source=source)
    invalidate_index()
    return {"ok": True}


# ---------------------------------------------------------------- ops


class OpAdd(BaseModel):
    op: str = "add"
    paths: list = []
    at: int | None = None


class OpRemove(BaseModel):
    op: str = "remove"
    ids: list = []


class OpMove(BaseModel):
    op: str = "move"
    ids: list = []
    to: int = 0
    at: int | None = None  # alias for `to`; final index of the first moved item


class OpsRequest(BaseModel):
    etag: str | None = None
    ops: list = []


@router.post("/api/playlists/{name}/ops")
def playlist_ops(name: str, body: OpsRequest):
    """Apply add / remove / move ops to a playlist, atomically.

    Request: {etag?, ops:[{op:"add",paths:[...],at?} |
                          {op:"remove",ids:[...]} |
                          {op:"move",ids:[...],to?|at?}]}
    Response: {etag, ops:[...applied with results...]}

    For `move`, `to` (alias `at`) is the final index of the first moved item
    in the resulting list, after the moved items are popped.
    """
    pl_dir = playlists_path()
    path = confine(pl_dir, name)
    if path is None or not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)

    # etag guard
    current_etag = _etag(path)
    if body.etag is not None and body.etag != current_etag:
        return JSONResponse({"error": "etag mismatch"}, status_code=409)

    # snapshot before mutating
    _snapshot(name, op_type="ops")

    # read current entries
    entries_raw, source, edited = read_entries(path)
    detached = _read_detached(path)
    is_synced = source.startswith("spotify:") or source.startswith("soundcloud:") and not detached

    applied = []

    for op in body.ops:
        otype = op.get("op") if isinstance(op, dict) else None

        if otype == "add":
            paths = op.get("paths") or []
            at = op.get("at")
            new_entries = []
            for p in paths:
                # validate path is inside the crate
                root = crate_root()
                cand = resolve_in(root, p)
                if cand is None:
                    continue  # skip paths outside the crate or not on disk
                tags = read_tags(cand) or {}
                rel = to_rel(cand, os.path.dirname(path)) or os.path.basename(cand)
                new_entries.append(
                    {
                        "track_id": "",
                        "artist": tags.get("artist") or "",
                        "title": tags.get("title") or "",
                        "length": float(tags.get("length") or 0),
                        "rel": rel,
                        "path": cand,
                        "exists": True,
                        "local": True,  # app-added entries are local
                        "extinf": None,
                    }
                )
            if at is None or at >= len(entries_raw):
                entries_raw.extend(new_entries)
            else:
                entries_raw[at:at] = new_entries
            applied.append({"op": "add", "paths": paths, "added": len(new_entries), "at": at})

        elif otype == "remove":
            ids = op.get("ids") or []
            removed = []
            for i in sorted(ids, reverse=True):
                if 0 <= i < len(entries_raw):
                    removed.append(entries_raw.pop(i))
            applied.append({"op": "remove", "ids": ids, "removed": len(removed)})

        elif otype == "move":
            ids = op.get("ids") or []
            # `to` is the final index of the first moved item in the resulting
            # list (after the moved items are popped). `at` is accepted as an
            # alias so move-to-top/bottom can reuse the same op.
            to = op.get("to", op.get("at", 0))
            moved = []
            for i in sorted(ids, reverse=True):
                if 0 <= i < len(entries_raw):
                    moved.append(entries_raw.pop(i))
            moved.reverse()  # restore original relative order
            # 'to' is relative to the list after removal
            to = max(0, min(to, len(entries_raw)))
            entries_raw[to:to] = moved
            applied.append({"op": "move", "ids": ids, "to": to, "moved": len(moved)})

        else:
            applied.append({"op": otype, "error": "unknown op"})

    # write back
    write_entries = []
    for e in entries_raw:
        write_entries.append(
            {
                "track_id": e.get("track_id", ""),
                "artist": e.get("artist", ""),
                "title": e.get("title", ""),
                "length": float(e.get("length") or 0),
                "rel": e.get("rel", ""),
                "path": e.get("path"),
                "local": bool(e.get("local")),
                "extinf": e.get("extinf"),
            }
        )

    new_source = source
    new_edited = edited
    if is_synced:
        new_edited = True
        # any entry without a track_id and not already local is a local addition
        for e in write_entries:
            if not e.get("track_id") and not e.get("local"):
                e["local"] = True

    write_m3u8(path, write_entries, source=new_source, edited=new_edited)
    invalidate_index()

    return {"etag": _etag(path), "ops": applied}


# ---------------------------------------------------------------- relink


class RelinkRequest(BaseModel):
    pass


@router.post("/api/playlists/{name}/relink")
def relink_playlist(name: str):
    """Relink missing (ghost) entries: try basename matching against the
    catalog, then synthetic-row matching via MatchIndex.  Returns a report of
    what was relocated / is ambiguous / still missing."""
    pl_dir = playlists_path()
    path = confine(pl_dir, name)
    if path is None or not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)

    _ensure_index_loaded()

    entries_raw, source, edited = read_entries(path)

    # build a by-basename index from the crate
    index = get_index(archive_path(), exports_dir())
    by_base = _build_by_base_index(index, archive_path())

    relocated = []
    ambiguous = []
    still_missing = []
    changed = False

    for i, e in enumerate(entries_raw):
        if e.get("exists"):
            continue
        rel = e.get("rel") or ""
        basename = rel.rsplit("/", 1)[-1] if rel else ""
        if not basename:
            still_missing.append(
                {"id": i, "rel": rel, "artist": e.get("artist", ""), "title": e.get("title", ""), "reason": "no basename"}
            )
            continue

        # synthesize a link dict for _classify_link
        link = {"path": rel, "basename": basename, "artist": e.get("artist", ""), "title": e.get("title", "")}
        status, value = _classify_link(link, by_base)
        if status == "relocated":
            # resolve the crate-relative path to an absolute path
            full = os.path.join(archive_path(), *value.split("/"))
            entries_raw[i]["path"] = full
            entries_raw[i]["exists"] = True
            entries_raw[i]["rel"] = value
            # update tags from the file
            tags = read_tags(full) or {}
            entries_raw[i]["artist"] = tags.get("artist") or e.get("artist", "")
            entries_raw[i]["title"] = tags.get("title") or e.get("title", "")
            entries_raw[i]["length"] = float(tags.get("length") or e.get("length") or 0)
            relocated.append({"id": i, "rel": rel, "new_rel": value})
            changed = True
        elif status == "ambiguous":
            ambiguous.append({"id": i, "rel": rel, "candidates": value})
        else:
            # try synthetic-row matching via MatchIndex
            length = float(e.get("length") or 0)
            synth_row = {
                "spotify_url": "",
                "track_id": "",
                "track_name": e.get("title") or "",
                "artist_names": e.get("artist") or "",
                "album_name": "",
                "duration_ms": int(length * 1000) if length else 0,
            }
            mindex = MatchIndex(index, links={}, library_root=archive_path())
            matched_entry, tier = mindex.match(synth_row)
            if matched_entry is not None:
                mp = matched_entry.get("path")
                if mp:
                    entries_raw[i]["path"] = mp
                    entries_raw[i]["exists"] = True
                    entries_raw[i]["rel"] = to_rel(mp, os.path.dirname(path)) or os.path.basename(mp)
                    entries_raw[i]["artist"] = matched_entry.get("artist") or e.get("artist", "")
                    entries_raw[i]["title"] = matched_entry.get("title") or e.get("title", "")
                    entries_raw[i]["length"] = float(matched_entry.get("length") or length)
                    relocated.append({"id": i, "rel": rel, "new_rel": entries_raw[i]["rel"], "tier": tier})
                    changed = True
                else:
                    still_missing.append(
                        {"id": i, "rel": rel, "artist": e.get("artist", ""), "title": e.get("title", ""), "reason": "no path"}
                    )
            else:
                still_missing.append(
                    {"id": i, "rel": rel, "artist": e.get("artist", ""), "title": e.get("title", ""), "reason": "not found"}
                )

    if changed:
        write_entries = []
        for e in entries_raw:
            write_entries.append(
                {
                    "track_id": e.get("track_id", ""),
                    "artist": e.get("artist", ""),
                    "title": e.get("title", ""),
                    "length": float(e.get("length") or 0),
                    "rel": e.get("rel", ""),
                    "path": e.get("path"),
                    "local": bool(e.get("local")),
                    "extinf": e.get("extinf"),
                }
            )
        write_m3u8(path, write_entries, source=source, edited=edited)
        invalidate_index()

    return {
        "relocated": relocated,
        "ambiguous": ambiguous,
        "missing": still_missing,
    }


# ---------------------------------------------------------------- detach / reattach


@router.post("/api/playlists/{name}/detach")
def detach_playlist(name: str):
    """Turn a synced playlist into a detached one: source=local +
    #TAPEDECK-DETACHED:<original source>.  Sync skips detached playlists."""
    pl_dir = playlists_path()
    path = confine(pl_dir, name)
    if path is None or not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)

    entries_raw, source, edited = read_entries(path)
    if not (source.startswith("spotify:") or source.startswith("soundcloud:")):
        return JSONResponse({"error": "not a synced playlist"}, status_code=400)
    if _read_detached(path):
        return JSONResponse({"error": "already detached"}, status_code=400)

    _snapshot(name, op_type="detach")

    new_entries = []
    for e in entries_raw:
        new_entries.append(
            {
                "track_id": e.get("track_id", ""),
                "artist": e.get("artist", ""),
                "title": e.get("title", ""),
                "length": float(e.get("length") or 0),
                "rel": e.get("rel", ""),
                "path": e.get("path"),
                "local": bool(e.get("local")),
                "extinf": e.get("extinf"),
            }
        )
    write_m3u8(path, new_entries, source="local", edited=False)
    # add the DETACHED header by re-writing with it: read_entries strips it,
    # so we need to inject it.  Simplest: prepend to the rendered text.
    # We do this by reading the file back and inserting the header line.
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")
    # insert DETACHED after the SOURCE line (which is after #EXTM3U)
    out = []
    inserted = False
    for line in lines:
        out.append(line)
        if line.startswith("#TAPEDECK-SOURCE:") and not inserted:
            out.append(f"#TAPEDECK-DETACHED:{source}")
            inserted = True
    _restore_text(path, "\n".join(out))
    invalidate_index()
    return {"ok": True, "kind": "detached", "source_id": source}


@router.post("/api/playlists/{name}/reattach")
def reattach_playlist(name: str, body: dict = Body(...)):
    """Reattach a detached playlist to its Spotify source.

    mode="merge": keep local additions, re-inserted after their previous
    neighbour (from the synced order).
    mode="replace": drop local additions, take Spotify's order wholesale.

    Dry-runs via plan_playlist() first: reports K new on Spotify, N local kept,
    M removed locally will return.
    """
    pl_dir = playlists_path()
    path = confine(pl_dir, name)
    if path is None or not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)

    entries_raw, source, edited = read_entries(path)
    detached = _read_detached(path)
    if not detached:
        return JSONResponse({"error": "not a detached playlist"}, status_code=400)

    mode = (body or {}).get("mode", "merge")
    if mode not in ("merge", "replace"):
        return JSONResponse({"error": "mode must be 'merge' or 'replace'"}, status_code=400)

    # source is like "spotify:<id>" or "soundcloud:<id>"
    service, _, source_id = detached.partition(":")
    if not source_id:
        return JSONResponse({"error": "invalid detached source"}, status_code=400)

    _snapshot(name, op_type="reattach")

    # build Spotify's current order from cached CSVs (offline, no network)
    index = get_index(archive_path(), exports_dir())
    mindex = MatchIndex(index, links={}, library_root=archive_path())

    # read playlist_tracks.csv for this playlist
    pl_rows = _playlist_tracks_rows(source_id, service)

    meta = {"id": source_id, "name": name}
    spotify_entries, _unmatched = plan_playlist(meta, pl_rows, mindex)

    # current local entries (with paths)
    local_entries = []
    for e in entries_raw:
        local_entries.append(
            {
                "track_id": e.get("track_id", ""),
                "artist": e.get("artist", ""),
                "title": e.get("title", ""),
                "length": float(e.get("length") or 0),
                "rel": e.get("rel", ""),
                "path": e.get("path"),
                "local": bool(e.get("local")),
                "extinf": e.get("extinf"),
            }
        )

    # count local additions: entries with local=True or no track_id
    local_added = [e for e in local_entries if e.get("local") or not e.get("track_id")]
    spotify_paths = {os.path.normpath(e.get("path", "")) for e in spotify_entries if e.get("path")}

    # Spotify tracks not currently in the local playlist
    new_on_spotify = [
        e
        for e in spotify_entries
        if e.get("path")
        and os.path.normpath(e["path"]) not in {os.path.normpath(le.get("path", "")) for le in local_entries if le.get("path")}
    ]

    # Local tracks not in Spotify's order
    removed_locally = [e for e in local_added if e.get("path") and os.path.normpath(e["path"]) not in spotify_paths]

    if mode == "replace":
        final_entries = spotify_entries
        kept = 0
    else:  # merge
        # re-insert local additions after their previous non-local neighbour
        # in the Spotify list; anchor gone -> append at end
        new_by_path = {}
        for e in spotify_entries:
            p = e.get("path")
            if p:
                new_by_path[os.path.normpath(p)] = e

        insert_after = {}
        # anchor = previous neighbour in the *current* local playlist
        # (the entry just before this local one that isn't itself local)
        for i, old in enumerate(local_entries):
            if not (old.get("local") or not old.get("track_id")):
                continue
            anchor = None
            for j in range(i - 1, -1, -1):
                if not (local_entries[j].get("local") or not local_entries[j].get("track_id")):
                    anchor = local_entries[j]
                    break
            anchor_path = os.path.normpath(anchor["path"]) if anchor and anchor.get("path") else None
            insert_after.setdefault(anchor_path, []).append(old)

        result = []
        for e in spotify_entries:
            result.append(e)
            p = os.path.normpath(e.get("path", "")) if e.get("path") else None
            for local_e in insert_after.pop(p, []):
                result.append(local_e)
        for local_e in insert_after.pop(None, []):
            result.append(local_e)
        final_entries = result
        kept = len(local_added)

    write_m3u8(path, final_entries, source=detached, edited=False)
    invalidate_index()

    return {
        "ok": True,
        "kind": "synced",
        "source_id": detached,
        "mode": mode,
        "new_on_spotify": len(new_on_spotify),
        "local_kept": kept if mode == "merge" else 0,
        "removed_locally": len(removed_locally),
    }


def _playlist_tracks_rows(playlist_id, service):
    """Read rows for one playlist from playlist_tracks.csv in the exports dir."""
    exports = exports_dir()
    if service == "soundcloud":
        tracks_csv = os.path.join(exports, "soundcloud", "playlist_tracks.csv")
    else:
        svc_dir = _spotify_exports_dir(exports)
        tracks_csv = os.path.join(svc_dir, "playlist_tracks.csv")
    if not os.path.isfile(tracks_csv):
        return []
    rows = []
    with open(tracks_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("playlist_id") == playlist_id:
                rows.append(row)
    return rows


def _spotify_exports_dir(exports_dir_value):
    new = os.path.join(exports_dir_value, "spotify")
    if os.path.isfile(os.path.join(new, "playlists.csv")):
        return new
    if os.path.isfile(os.path.join(exports_dir_value, "playlists.csv")):
        return exports_dir_value
    return new


# ---------------------------------------------------------------- refresh / rebuild


@router.post("/api/playlists/{name}/refresh")
def refresh_playlist(name: str):
    """Rescrape a single synced playlist from the network and rebuild its
    .m3u8.  Synced only."""
    pl_dir = playlists_path()
    path = confine(pl_dir, name)
    if path is None or not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)

    entries_raw, source, edited = read_entries(path)
    if not (source.startswith("spotify:") or source.startswith("soundcloud:")):
        return JSONResponse({"error": "not a synced playlist"}, status_code=400)
    if _read_detached(path):
        return JSONResponse({"error": "detached playlists cannot be refreshed"}, status_code=400)

    service, _, source_id = source.partition(":")
    if not source_id:
        return JSONResponse({"error": "invalid source"}, status_code=400)

    _snapshot(name, op_type="refresh")

    try:
        result = build_playlists(
            apply=True,
            names=[source_id],
            rescrape=True,
            playlists_path=playlists_path(),
            archive_path=crate_root(),
            exports_dir=exports_dir(),
            service=service,
            keep_local=True,
            verbose=False,
        )
    except Exception as exc:
        return JSONResponse({"error": f"refresh failed: {exc}"}, status_code=500)

    invalidate_index()
    return {"ok": True, "kind": "synced", "source_id": source, "result": result}


@router.post("/api/playlists/{name}/rebuild")
def rebuild_playlist(name: str):
    """Rebuild a synced playlist from cached CSVs (offline, no network).
    Useful after linking a ghost.  Synced only."""
    pl_dir = playlists_path()
    path = confine(pl_dir, name)
    if path is None or not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)

    entries_raw, source, edited = read_entries(path)
    if not (source.startswith("spotify:") or source.startswith("soundcloud:")):
        return JSONResponse({"error": "not a synced playlist"}, status_code=400)
    if _read_detached(path):
        return JSONResponse({"error": "detached playlists cannot be rebuilt"}, status_code=400)

    service, _, source_id = source.partition(":")
    if not source_id:
        return JSONResponse({"error": "invalid source"}, status_code=400)

    _snapshot(name, op_type="rebuild")

    try:
        result = build_playlists(
            apply=True,
            names=[source_id],
            rescrape=False,
            playlists_path=playlists_path(),
            archive_path=crate_root(),
            exports_dir=exports_dir(),
            service=service,
            keep_local=True,
            verbose=False,
        )
    except Exception as exc:
        return JSONResponse({"error": f"rebuild failed: {exc}"}, status_code=500)

    invalidate_index()
    return {"ok": True, "kind": "synced", "source_id": source, "result": result}


# ---------------------------------------------------------------- sync preview


@router.get("/api/sync/preview")
def sync_preview():
    """For each synced playlist: what the next sync would drop / add,
    computed from the cached CSV exports (no network)."""
    _ensure_index_loaded()

    index = get_index(archive_path(), exports_dir())
    mindex = MatchIndex(index, links={}, library_root=archive_path())

    pl_dir = playlists_path()
    previews = []
    if os.path.isdir(pl_dir):
        for name in sorted(os.listdir(pl_dir)):
            if not name.lower().endswith((".m3u", ".m3u8")):
                continue
            path = os.path.join(pl_dir, name)
            entries_raw, source, edited = read_entries(path)
            if not (source.startswith("spotify:") or source.startswith("soundcloud:")):
                continue
            if _read_detached(path):
                continue

            service, _, source_id = source.partition(":")
            pl_rows = _playlist_tracks_rows(source_id, service)
            meta = {"id": source_id, "name": name}
            spotify_entries, _unmatched = plan_playlist(meta, pl_rows, mindex)

            # current entries by path_key
            current_paths = {}
            for e in entries_raw:
                p = e.get("path")
                if p:
                    current_paths[path_key(p)] = e

            spotify_paths = {}
            for e in spotify_entries:
                p = e.get("path")
                if p:
                    spotify_paths[path_key(p)] = e

            drops = [e for e in entries_raw if e.get("path") and path_key(e["path"]) not in spotify_paths]
            adds = [e for e in spotify_entries if e.get("path") and path_key(e["path"]) not in current_paths]

            previews.append(
                {
                    "name": name,
                    "source_id": source,
                    "edited": edited,
                    "drops": len(drops),
                    "adds": len(adds),
                    "drop_details": [
                        {"rel": e.get("rel", ""), "artist": e.get("artist", ""), "title": e.get("title", "")} for e in drops
                    ],
                    "add_details": [
                        {"rel": e.get("rel", ""), "artist": e.get("artist", ""), "title": e.get("title", "")} for e in adds
                    ],
                }
            )

    return {"playlists": previews}


# ---------------------------------------------------------------- links


class LinkRequest(BaseModel):
    url: str
    path: str
    artist: str = ""
    title: str = ""


@router.post("/api/links")
def add_link_endpoint(body: LinkRequest):
    """Associate a track URL with an existing crate file (.manual_links.json).
    Used to fix ghost rows on playlists."""
    try:
        rel = _add_link(
            body.url,
            body.path,
            artist=body.artist,
            title=body.title,
        )
    except LinkRejected as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except LinksError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return {"ok": True, "path": rel}
