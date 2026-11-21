"""app.main - FastAPI app for the tapebuilding crate-management web UI.

Thin import layer over `lib/` and the domain packages: no subprocess, no
shelling out to CLIs it doesn't own. Routes live in `app.routers.*`; the
scan cache and the runner names the HTTP tests poke live here.

Run:

    uv run app

(equivalently `PYTHONPATH=src uv run uvicorn app.main:app --reload --port 8000`)

The site title comes from the TITLE env var (default "tapedeck").
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

import os
import threading
from pathlib import Path

from app.config import APP_TITLE, STATIC_DIR
from app.routers import files, jobs as jobs_router, library, pages, playlists
from lib.paths import archive_path, playlists_path
from lib.tags import scan_audio

app = FastAPI(title=APP_TITLE)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ------------------------------------------------------------------ SPA build
# The React UI (Vite) builds to ``src/app/ui/dist``. Mount its asset
# subdirectory so hashed JS/CSS are served with proper headers, then fall
# through to ``dist/index.html`` for any non-API path so client-side routing
# works (refresh on /playlists/foo, etc.). The mount only happens if dist
# exists (it's produced by `npm run build`, which requires `npm install`).
_DIST_DIR = Path(__file__).resolve().parent.parent / "app" / "ui" / "dist"
if _DIST_DIR.is_dir():
    _ASSETS_DIR = _DIST_DIR / "assets"
    if _ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="spa-assets")

app.include_router(pages.router)
app.include_router(library.router)
app.include_router(files.router)
app.include_router(playlists.router)
app.include_router(jobs_router.router)

# runner names kept as module attributes so the test suite can patch
# main_module._run_download etc. to no-ops.

# ------------------------------------------------------------------ health

@app.get("/api/health")
def health():
    problems = []
    crate = archive_path()
    if not crate or not os.path.isdir(crate):
        problems.append(f"crate not found: {crate}")
    try:
        pl = playlists_path()
        if not os.path.isdir(pl):
            problems.append(f"playlists dir not found: {pl}")
    except ValueError as exc:
        problems.append(str(exc))
    return {
        "ok": not problems,
        "crate": crate,
        "playlists": playlists_path() if not problems else None,
        "problems": problems,
    }


# ---------------------------------------------------------------- library
# scan cache: the crate can hold 10k+ files and scan_audio reads every tag,
# so we cache in memory and scan on a background thread. the first load
# returns "scanning" immediately; subsequent loads are instant from cache.
# The library router reads this state lazily at request time.

_lib_scan_cache = {"files": None, "scanning": False, "error": None}
_lib_scan_lock = threading.Lock()


def _scan_library_bg():
    try:
        files = scan_audio(archive_path())
        with _lib_scan_lock:
            _lib_scan_cache["files"] = files
            _lib_scan_cache["error"] = None
    except Exception as exc:  # keep the error so the frontend can surface it
        with _lib_scan_lock:
            _lib_scan_cache["error"] = str(exc)
    finally:
        with _lib_scan_lock:
            _lib_scan_cache["scanning"] = False


def _start_scan():
    with _lib_scan_lock:
        if _lib_scan_cache["scanning"]:
            return
        _lib_scan_cache["scanning"] = True
        # keep serving the previous cached files until the new scan lands, so a
        # rescan never leaves the library looking empty mid-flight
        _lib_scan_cache["error"] = None
    threading.Thread(target=_scan_library_bg, daemon=True).start()


# ---------------------------------------------------------------- SPA fallback
# Serve the built React SPA for any route not handled by the API routers.
# Registered LAST so /api, /files, /static, /assets all take precedence.
if _DIST_DIR.is_dir():

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def spa_fallback(full_path: str):
        """Serve index.html for any non-API path so client-side routing works."""
        if full_path.startswith(("api/", "files/", "static/", "assets/")):
            return Response(status_code=404)
        return FileResponse(str(_DIST_DIR / "index.html"))
