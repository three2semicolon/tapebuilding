"""app.jobs - in-process job store: one background thread per job, stdout capture.

Jobs run serially through a single worker thread so that stdout capture and
any crate-touching work never collide with itself. Each job:

    {'id', 'type', 'state': queued|running|ok|error,
     'log': [...], 'progress': {'current','total','pct'}, 'result': ...,
     'error': None, 'meta': {...}, 'created_at', 'updated_at'}

The job function receives the job dict and can:
  - call job['log'].append(...) / use print() (stdout is redirected into the log)
  - set job['progress'] = {...}
  - set job['result'] = ...
"""
import io
import sys
import threading
import time
import uuid


class JobLogStream(io.TextIOBase):
    """file-like object that appends each line to a job's log as it's written."""
    def __init__(self, job, store):
        self.job = job
        self.store = store
        self._buffer = ""

    def write(self, s):
        if not s:
            return 0
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.store._log(self.job, line)
        return len(s)

    def flush(self):
        if self._buffer.strip():
            self.store._log(self.job, self._buffer)
            self._buffer = ""

    def reconfigure(self, *args, **kwargs):
        """TextIOWrapper-compatible hook.

        organize.preimport.stage() calls sys.stdout.reconfigure(encoding=...)
        at startup. under the job store's stdout capture (a plain TextIOBase)
        that would raise AttributeError, so accept and ignore it - prints still
        flow into the job log via write().
        """
        pass


class JobStore:
    def __init__(self):
        self._jobs = {}
        self._lock = threading.RLock()
        self._queue = []
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    # --- public API ---------------------------------------------------
    def create(self, job_type, meta=None):
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "type": job_type,
            "state": "queued",
            "log": [],
            "progress": {"current": 0, "total": 0, "pct": 0},
            "result": None,
            "error": None,
            "meta": meta or {},
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        with self._lock:
            self._jobs[job_id] = job
        return job

    def enqueue(self, job_type, fn, meta=None):
        job = self.create(job_type, meta)
        job["_fn"] = fn
        with self._lock:
            self._queue.append(job)
        return job["id"]

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            # return a shallow copy minus the internal callable
            out = dict(job)
            out.pop("_fn", None)
            return out

    def list(self):
        with self._lock:
            jobs = list(self._jobs.values())
        out = []
        for job in jobs:
            item = dict(job)
            item.pop("_fn", None)
            out.append(item)
        out.sort(key=lambda j: j["created_at"], reverse=True)
        return out

    def delete(self, job_id):
        with self._lock:
            self._jobs.pop(job_id, None)

    # --- internals ----------------------------------------------------
    def _log(self, job, line):
        with self._lock:
            job["log"].append(str(line))
            job["updated_at"] = time.time()

    def _pump(self):
        while True:
            with self._lock:
                job = self._queue.pop(0) if self._queue else None
            if job is None:
                time.sleep(0.3)
                continue
            self._execute(job)

    def _execute(self, job):
        job["state"] = "running"
        job["updated_at"] = time.time()
        stream = JobLogStream(job, self)
        old_stdout = sys.stdout
        sys.stdout = stream
        try:
            job["_fn"](job)
            if job["state"] == "running":
                job["state"] = "ok"
        except Exception as exc:  # noqa: BLE001 - surface any job failure as error state
            job["state"] = "error"
            job["error"] = str(exc)
            self._log(job, f"ERROR: {exc}")
        finally:
            stream.flush()
            sys.stdout = old_stdout
            job["updated_at"] = time.time()


job_store = JobStore()
