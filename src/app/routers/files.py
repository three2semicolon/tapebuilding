"""app.routers.files - serving crate audio over HTTP at /files/<path>.

Only audio extensions are served and every path is confined to the crate
root, so a Discord bot on the same LAN can play crate tracks via
``http://<host>:8000/files/...`` links.
"""
import mimetypes
import os
from urllib.parse import unquote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from lib.paths import archive_path
from lib.tags import EXTENSIONS

router = APIRouter()


def _crate_file(path):
    """resolve a /files/... request to an audio file inside the crate root."""
    root = os.path.realpath(archive_path())
    segments = [unquote(seg) for seg in path.split("/") if seg not in ("", ".", "..")]
    if not segments:
        return None
    candidate = os.path.realpath(os.path.join(root, *segments))
    try:
        inside = os.path.commonpath([candidate, root]) == root
    except ValueError:
        inside = False
    if not inside or not os.path.isfile(candidate):
        return None
    if os.path.splitext(candidate)[1].lower() not in EXTENSIONS:
        return None
    return candidate


def _file_range(candidate, start, end, chunk=8192):
    """yield ``[start, end]`` of a file in chunks, for 206 responses."""
    with open(candidate, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = f.read(min(chunk, remaining))
            if not data:
                break
            yield data
            remaining -= len(data)


@router.get("/files/{path:path}")
def crate_file(request: Request, path: str):
    candidate = _crate_file(path)
    if candidate is None:
        return Response(status_code=404)
    size = os.path.getsize(candidate)
    media_type = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes"}

    range_header = request.headers.get("range", "")
    if range_header.lower().startswith("bytes="):
        spec = range_header[6:].strip()
        if "-" in spec and "," not in spec:  # single range only
            first, _, last = spec.partition("-")
            try:
                start = int(first) if first else 0
                end = int(last) if last else size - 1
            except ValueError:
                start, end = 0, size - 1
            if start < 0:
                start = max(0, size + start)
            if end >= size:
                end = size - 1
            if 0 <= start <= end < size:
                return StreamingResponse(
                    _file_range(candidate, start, end),
                    status_code=206,
                    media_type=media_type,
                    headers={
                        **headers,
                        "Content-Range": f"bytes {start}-{end}/{size}",
                    },
                )

    return FileResponse(
        candidate,
        media_type=media_type,
        content_disposition_type="inline",
        headers=headers,
    )
