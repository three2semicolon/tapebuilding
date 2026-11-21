"""app.routers.jobs - job enqueue/list/get/delete and the playlist sync job.

Jobs run serially through a single worker thread in ``app.jobs`` so that
stdout capture and any crate-touching work never collide with itself.

The runner functions are resolved lazily from ``app.main`` at request time
so the test suite can monkeypatch ``main_module._run_*`` to no-ops and the
HTTP layer is exercised without touching the crate or the network.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.jobs import job_store

router = APIRouter()


def _runners():
    from app.main import (
        _run_cleanup,
        _run_download,
        _run_import,
        _run_organize,
        _run_preimport,
        _run_sync,
        _run_validate,
    )
    return {
        "download": _run_download,
        "sync": _run_sync,
        "cleanup": _run_cleanup,
        "validate": _run_validate,
        "preimport": _run_preimport,
        "import": _run_import,
        "organize": _run_organize,
    }


@router.post("/api/jobs")
def create_job(job_type: str, target: str = "", organize: str = ""):
    def _run(job):
        job["progress"] = {"current": 0, "total": 1, "pct": 0}
        job["log"].append(f"starting {job_type} ...")
        runners = _runners()
        fn = runners.get(job_type)
        if fn is None:
            job["log"].append(f"unknown job type: {job_type}")
            raise ValueError(f"unknown job type: {job_type}")
        if job_type == "download":
            fn(job, target, organize=organize)
        else:
            fn(job)
        job["progress"] = {"current": 1, "total": 1, "pct": 100}
        job["log"].append("done.")
        job["result"] = {"type": job_type, "target": target}

    job_id = job_store.enqueue(job_type, _run, meta={"target": target, "organize": organize})
    return {"id": job_id}


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return job


@router.get("/api/jobs")
def list_jobs():
    return {"jobs": job_store.list()}


@router.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job_store.delete(job_id)
    return {"ok": True}


@router.post("/api/playlists/sync")
def sync_playlists():
    def _run(job):
        job["progress"] = {"current": 0, "total": 1, "pct": 0}
        job["log"].append("starting sync ...")
        _runners()["sync"](job)
        job["progress"] = {"current": 1, "total": 1, "pct": 100}
        job["log"].append("done.")
        job["result"] = {"type": "sync", "target": ""}

    job_id = job_store.enqueue("sync", _run, meta={"target": "", "organize": ""})
    return {"id": job_id}
