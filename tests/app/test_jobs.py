"""Behavioral tests for the web app's /api/jobs endpoints (app/main.py).

Jobs run through a background pump thread in app.jobs, so the run hooks are
patched to no-ops via the `client` fixture - we test the HTTP layer
(enqueue, list, get, delete), not spotdl/yt-dlp/cleanup/validate themselves.

The original bug: create_job() declares job_type as a query parameter, so a
POST without ?job_type= must return 422, and a POST with ?job_type= must
enqueue a job whose meta.target is preserved.
"""

import time


def _settled(client, job_id: str, timeout: float = 5.0):
    """Poll until the job leaves the queued/running states."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client("GET", f"/api/jobs/{job_id}")
        if resp.status_code == 404:
            return resp
        state = resp.json().get("state")
        if state not in ("queued", "running"):
            return resp
        time.sleep(0.1)
    return client("GET", f"/api/jobs/{job_id}")


def test_create_job_requires_job_type(client):
    resp = client("POST", "/api/jobs")
    assert resp.status_code == 422


def test_create_job_download(client):
    resp = client(
        "POST",
        "/api/jobs?job_type=download&target=https%3A%2F%2Fopen.spotify.com%2Ftrack%2Fabc",
    )
    assert resp.status_code == 200
    job_id = resp.json()["id"]
    assert job_id

    job = _settled(client, job_id).json()
    assert job["id"] == job_id
    assert job["type"] == "download"
    assert job["state"] == "ok"
    assert job["meta"]["target"] == "https://open.spotify.com/track/abc"


def test_create_job_sync(client):
    resp = client("POST", "/api/jobs?job_type=sync")
    assert resp.status_code == 200
    job_id = resp.json()["id"]
    job = _settled(client, job_id).json()
    assert job["type"] == "sync"
    assert job["state"] == "ok"


def test_create_job_unknown_type(client):
    resp = client("POST", "/api/jobs?job_type=nope")
    assert resp.status_code == 200
    job_id = resp.json()["id"]
    job = _settled(client, job_id).json()
    assert job["state"] == "error"


def test_create_job_preimport(client):
    resp = client("POST", "/api/jobs?job_type=preimport")
    assert resp.status_code == 200
    job_id = resp.json()["id"]
    job = _settled(client, job_id).json()
    assert job["type"] == "preimport"
    assert job["state"] == "ok"


def test_create_job_import(client):
    resp = client("POST", "/api/jobs?job_type=import")
    assert resp.status_code == 200
    job_id = resp.json()["id"]
    job = _settled(client, job_id).json()
    assert job["type"] == "import"
    assert job["state"] == "ok"


def test_create_job_organize(client):
    resp = client("POST", "/api/jobs?job_type=organize")
    assert resp.status_code == 200
    job_id = resp.json()["id"]
    job = _settled(client, job_id).json()
    assert job["type"] == "organize"
    assert job["state"] == "ok"


def test_list_jobs(client):
    client("POST", "/api/jobs?job_type=download&target=x")
    client("POST", "/api/jobs?job_type=sync")
    jobs = client("GET", "/api/jobs").json()["jobs"]
    assert len(jobs) >= 2


def test_get_job_not_found(client):
    assert client("GET", "/api/jobs/does-not-exist").status_code == 404


def test_delete_job(client):
    resp = client("POST", "/api/jobs?job_type=download&target=x")
    job_id = resp.json()["id"]
    assert client("DELETE", f"/api/jobs/{job_id}").status_code == 200
    assert client("GET", f"/api/jobs/{job_id}").status_code == 404
