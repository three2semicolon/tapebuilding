"""app.routers.library - library browsing, tag edits, moves and cover art.

the listing is served from ``app.services.library_index.LibraryIndex``, an
in-memory crate index loaded from the shared :func:`lib.catalog.indexer.refresh_index`.
the scan cache in ``app.main`` is kept only for the scanning-state flag and
error reporting so a rescan never leaves the library looking empty mid-flight.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from urllib.parse import quote

import os

from app.services.guard import confine, resolve_in
from app.services.library_index import LibraryIndex
from app.services.membership import build_index
from lib.paths import archive_path, path_key
from lib.tags import read_cover, read_tags, safe_move, write_tag

router = APIRouter()

_lib_index = LibraryIndex()


def _cache():
    from app.main import _lib_scan_cache, _lib_scan_lock, _start_scan

    return _lib_scan_cache, _lib_scan_lock, _start_scan


def _add_url(rows):
    """attach a /files/<relpath> playable url to each row for the bot."""
    root = archive_path()
    out = []
    for r in rows:
        r = dict(r)
        p = r.get("path", "")
        try:
            rel = os.path.relpath(p, root)
        except ValueError:
            rel = p
        rel = rel.replace(os.sep, "/")
        r["url"] = "/files/" + quote(rel)
        out.append(r)
    return out


# ---------------------------------------------------------------- status

@router.get("/api/library/status")
def library_status():
    """index state: {state, scanned, read, total, error}."""
    return _lib_index.status()


# ---------------------------------------------------------------- listing

@router.get("/api/library")
def library(q: str = "", artist: str = "", album: str = "",
            playlist: str = "", min_playlists: int = 1,
            sort: str = "artist", dir: str = "asc",
            offset: int = 0, limit: int = 50):
    """paged, filterable, sortable view of the crate index.

    query params:
      q              substring match on artist + album + title
      artist         substring match on artist
      album          substring match on album
      playlist       <name> -> only tracks in that playlist;
                     "none" -> only tracks in no playlist
      min_playlists  only tracks in at least N playlists
      sort           artist|album|title|path
      dir            asc|desc
      offset/limit   paging
    """
    _lib_scan_cache, _lib_scan_lock, _start_scan = _cache()
    with _lib_scan_lock:
        scanning = _lib_scan_cache["scanning"]
        err = _lib_scan_cache["error"]

    if err:
        return {"total": 0, "rows": [], "archive_path": archive_path(),
                "scanning": False, "error": err}

    # kick off a load if the index is idle (cold start)
    if _lib_index.status()["state"] == "idle":
        _lib_index.load()

    membership = build_index()
    result = _lib_index.rows(
        q=q, artist=artist, album=album,
        playlist=playlist or None,
        min_playlists=min_playlists,
        sort=sort, dir=dir, offset=offset, limit=limit,
        membership=membership,
    )
    result["rows"] = _add_url(result.get("rows", []))
    result["archive_path"] = archive_path()
    result["scanning"] = scanning
    return result


@router.post("/api/library/rescan")
def rescan_library():
    """non-destructive rescan: reloads the index in the background while
    continuing to serve the last known data."""
    _lib_scan_cache, _lib_scan_lock, _start_scan = _cache()
    _start_scan()
    _lib_index.load(force=True)
    return {"scanning": True}


# ---------------------------------------------------------------- file

@router.get("/api/library/cover")
def library_cover(path: str):
    root = archive_path()
    candidate = resolve_in(root, path)
    if candidate is None:
        return Response(status_code=204)
    result = read_cover(candidate)
    if result:
        data, mime = result
        return Response(content=data, media_type=mime)
    return Response(status_code=204)


@router.get("/api/library/file")
def library_file(path: str):
    root = archive_path()
    candidate = resolve_in(root, path)
    if candidate is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    entry = _lib_index.by_path(path)
    if entry is None:
        entry = read_tags(candidate)
    return entry


@router.patch("/api/library/file")
def library_update(path: str, fields: dict):
    root = archive_path()
    candidate = resolve_in(root, path)
    if candidate is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        changed = write_tag(candidate, raise_errors=True, **fields)
    except Exception as exc:
        return JSONResponse({"error": f"tag write failed: {exc}"}, status_code=500)
    # patch the in-memory index so the next listing reflects the edit
    entry = _lib_index.by_path(candidate)
    if entry is not None:
        entry.update(read_tags(candidate) or {})
    # also patch the legacy scan cache for any callers still reading it
    _lib_scan_cache, _lib_scan_lock, _start_scan = _cache()
    with _lib_scan_lock:
        for e in _lib_scan_cache["files"] or []:
            if e.get("path") == candidate:
                e.update(read_tags(candidate) or {})
                break
    return {"ok": True, "changed": changed}


@router.post("/api/library/move")
def library_move(src: str, dst: str):
    root = archive_path()
    actual_src = resolve_in(root, src)
    if actual_src is None:
        return JSONResponse({"error": "source not found"}, status_code=404)
    actual_dst = confine(root, dst)
    if actual_dst is None:
        return JSONResponse({"error": "destination outside crate"}, status_code=400)
    actual = safe_move(actual_src, actual_dst)
    # patch the in-memory index so the moved file keeps its entry
    entry = _lib_index.by_path(actual_src)
    if entry is not None:
        entry["path"] = actual
        entry["_path_key"] = path_key(actual)
    # also patch the legacy scan cache
    _lib_scan_cache, _lib_scan_lock, _start_scan = _cache()
    with _lib_scan_lock:
        for e in _lib_scan_cache["files"] or []:
            if e.get("path") == actual_src:
                e["path"] = actual
                break
    return {"ok": True, "actual": actual}
