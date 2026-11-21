"""Fixtures for the app/ (web UI) tests.

app.main starts a JobStore with a background pump thread at import time, and
enqueued jobs actually run the download/sync/cleanup/validate hooks - which
touch the crate and the network. Those hooks are patched to no-ops here so
the tests exercise the HTTP layer (enqueue / list / get / delete) without
side effects.

starlette's TestClient is incompatible with the pinned httpx version here
(it passes `app=` to httpx.Client, which httpx 0.28 rejects), and ASGITransport
is async-only, so we drive the app with httpx.AsyncClient through asyncio.run.
"""

import asyncio
import httpx

import app.main as main_module
import pytest
from app.jobs import job_store


@pytest.fixture
def client(monkeypatch):
    for fn in (
        "_run_download",
        "_run_sync",
        "_run_cleanup",
        "_run_validate",
        "_run_preimport",
        "_run_import",
        "_run_organize",
    ):
        monkeypatch.setattr(main_module, fn, lambda job, *args, **kwargs: None)
    job_store._jobs.clear()
    job_store._queue.clear()

    transport = httpx.ASGITransport(app=main_module.app)

    async def _request(method, path, **kwargs):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            return await getattr(c, method.lower())(path, **kwargs)

    def request(method, path, **kwargs):
        return asyncio.run(_request(method, path, **kwargs))

    return request
