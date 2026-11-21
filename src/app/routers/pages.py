"""app.routers.pages - page routes and the config endpoint.

In Phase 4 the HTML page routes (/library, /download, /playlists, /jobs)
are replaced by the React SPA fallback in app.main. This module keeps only
/api/config and /favicon.ico.
"""
from fastapi import APIRouter
from fastapi.responses import Response

from app.config import APP_TITLE

router = APIRouter()


@router.get("/api/config")
def config():
    return {"title": APP_TITLE}


@router.get("/favicon.ico")
def favicon():
    return Response(status_code=204)
