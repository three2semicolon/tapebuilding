"""app.runners - background job runners for crate operations.

Each runner receives the job dict and can append to ``job["log"]``, set
``job["progress"]`` and ``job["result"]``. The runners are intentionally
thin: the real work lives in the domain packages they import lazily so the
web app imports light and the CLI is untouched.
"""
import datetime
import os
import shutil

from lib.paths import archive_path, playlists_path


def _snapshot_playlists(pl_dir):
    """copy current playlists into ``<pl_dir>/.history/<timestamp>/`` before a
    sync rewrites them, and prune older snapshots so only the ~10 most recent
    are kept."""
    try:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(pl_dir, ".history", stamp)
        os.makedirs(dest, exist_ok=True)
        if os.path.isdir(pl_dir):
            for name in os.listdir(pl_dir):
                if not name.lower().endswith((".m3u", ".m3u8")):
                    continue
                src = os.path.join(pl_dir, name)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(dest, name))
    except OSError:
        # a snapshot failure must never block a sync
        return
    # prune: keep the 10 most recent history snapshots
    try:
        history_dir = os.path.join(pl_dir, ".history")
        snaps = sorted(
            (d for d in os.listdir(history_dir)
             if os.path.isdir(os.path.join(history_dir, d))),
            reverse=True,
        )
        for old in snaps[10:]:
            shutil.rmtree(os.path.join(history_dir, old), ignore_errors=True)
    except OSError:
        pass


def _run_download(job, url, organize=""):
    """download_spotify / download_ytdl under a job.

    without ``organize`` the file lands in <crate>/unorganized (the staging
    drop) instead of the crate root - queue a preimport + import job to
    file it into the crate proper. when ``organize`` is set, runs the full
    pipeline (core.download.run_download_songs: download -> import ->
    playlists refresh) which already stages through unorganized/.
    """
    job["log"].append(f"url: {url}")
    crate = archive_path()
    unorganized_dir = os.path.join(crate, "unorganized")
    os.makedirs(unorganized_dir, exist_ok=True)
    if organize:
        job["log"].append("organize after download: running full pipeline ...")
        from core.download import run_download_songs
        result = run_download_songs(source=url, apply=True)
        job["result"] = {"ok": result["ok"], "steps": result.get("steps", [])}
        if not result["ok"]:
            raise RuntimeError("download pipeline returned errors")
    elif "spotify.com" in url or url.startswith("spotify:"):
        from download.spotify.spotify_download import download_spotify
        job["log"].append("routing to download_spotify (spotdl)")
        ok = download_spotify(urls=[url], output_dir=unorganized_dir)
    else:
        from download.ytdl import download_ytdl
        job["log"].append("routing to download_ytdl (yt-dlp)")
        ok = download_ytdl(url, output_dir=unorganized_dir)
    if not organize:
        job["result"] = {"ok": ok}
        if not ok:
            raise RuntimeError("download returned False")


def _run_sync(job):
    # snapshot playlists before the sync rewrites them, so a bad sync can be
    # rolled back from <playlists>/.history/<timestamp>/
    try:
        _snapshot_playlists(playlists_path())
    except ValueError:
        job["log"].append("sync: PLAYLISTS_PATH not set, skipping playlist snapshot")
    from core.sync import run_sync
    job["log"].append("running core sync ...")
    run_sync(verbose=True)
    job["log"].append("sync complete.")


def _run_cleanup(job):
    from organize.cleanup.apply import run_cleanup
    job["log"].append("running organize cleanup ...")
    run_cleanup(crate=archive_path(), apply=True, verbose=True)
    job["log"].append("cleanup complete.")


def _run_validate(job):
    from organize.validate import validate_all
    job["log"].append("running organize validate ...")
    validate_all(crate=archive_path(), apply=True, verbose=True)
    job["log"].append("validation complete.")


def _run_preimport(job):
    """stage <crate>/unorganized for a clean beets import (preimport pass)."""
    from organize.preimport import stage as preimport_stage
    crate = archive_path()
    unorganized = os.path.join(crate, "unorganized")
    job["log"].append(f"preimport: staging {unorganized}")
    result = preimport_stage(unorganized, crate, apply=True, verbose=True)
    job["result"] = {
        "ok": True,
        "staged_folders": len(result.get("staged_folders", [])),
        "merged_folders": len(result.get("merged_folders", [])),
    }
    job["log"].append(
        f"preimport complete: {job['result']['staged_folders']} folders staged, "
        f"{job['result']['merged_folders']} merged"
    )


def _run_import(job):
    """import staged <crate>/unorganized into the crate (beets two-pass
    import). skips preimport since that ran as its own step - re-running it
    here is idempotent but redundant."""
    from organize.beets_import import run_import
    crate = archive_path()
    unorganized = os.path.join(crate, "unorganized")
    job["log"].append(f"import: {unorganized} -> {crate}")
    result = run_import(
        unorganized,
        output_dir=crate,
        apply=True,
        no_preimport=True,
        verbose=True,
    )
    job["result"] = {"ok": bool(result.get("ok"))}
    if not result.get("ok"):
        raise RuntimeError("import failed")
    job["log"].append("import complete")


def _run_organize(job):
    """full organize pipeline: preimport -> import -> cleanup."""
    _run_preimport(job)
    job["log"].append("--- preimport done, starting import ---")
    _run_import(job)
    from organize.cleanup.apply import run_cleanup
    crate = archive_path()
    job["log"].append("running organize cleanup ...")
    run_cleanup(crate=crate, apply=True, verbose=True)
    job["log"].append("cleanup complete.")
