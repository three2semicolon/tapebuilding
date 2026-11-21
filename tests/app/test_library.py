"""Behavioral tests for the library routes added in Phase 0: tag edits, moves,
cover art, and path confinement against ``ARCHIVE_PATH``.

The scan cache is monkeypatched so these tests never touch a real crate; the
``write_tag``/``read_tags`` helpers are stubbed at the router module so no real
audio metadata is read or written. Real empty files are created on disk only so
that ``resolve_in`` (which requires an existing file) resolves them.
"""

from pathlib import Path

import app.main as main_module

from app.routers import library as library_module


def _stub_tags(monkeypatch, entries, write_ok=True):
    """stub read_tags/write_tag on the router module and seed the scan cache."""
    monkeypatch.setattr(
        library_module,
        "read_tags",
        lambda path: next((dict(e) for e in entries if e["path"] == path), None),
    )

    def _write_tag(path, raise_errors=False, **fields):
        for e in entries:
            if e["path"] == path:
                if not write_ok and raise_errors:
                    raise OSError("tag write boom")
                e.update(fields)
                return write_ok
        if raise_errors:
            raise FileNotFoundError(path)
        return False

    monkeypatch.setattr(library_module, "write_tag", _write_tag)


def _seed_cache(entries):
    main_module._lib_scan_cache["files"] = [dict(e) for e in entries]
    main_module._lib_scan_cache["scanning"] = False
    main_module._lib_scan_cache["error"] = None


def test_library_file_outside_crate_is_404(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    (root / "albums").mkdir(parents=True)
    track = root / "albums" / "inside.mp3"
    track.write_bytes(b"x")
    outside = tmp_path / "escape.txt"
    outside.write_bytes(b"secret")
    monkeypatch.setenv("ARCHIVE_PATH", str(root))

    assert client("GET", "/api/library/file", params={"path": str(outside)}).status_code == 404
    assert (
        client("GET", "/api/library/file", params={"path": str(root / "albums" / "../escape.txt")})
        .status_code
        == 404
    )
    # a real file inside the crate resolves (read_tags is stubbed -> dict)
    assert client("GET", "/api/library/file", params={"path": str(track)}).status_code == 200


def test_library_cover_outside_crate_is_204(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    root.mkdir()
    outside = tmp_path / "escape.jpg"
    outside.write_bytes(b"fake")
    monkeypatch.setenv("ARCHIVE_PATH", str(root))

    assert client("GET", "/api/library/cover", params={"path": str(outside)}).status_code == 204


def test_tag_write_success_patches_cache(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    (root / "albums").mkdir(parents=True)
    track = str(root / "albums" / "A - T.mp3")
    Path(track).write_bytes(b"x")
    entries = [{"path": track, "artist": "A", "album": "Album", "title": "T"}]
    _stub_tags(monkeypatch, entries, write_ok=True)
    _seed_cache(entries)
    monkeypatch.setenv("ARCHIVE_PATH", str(root))

    resp = client(
        "PATCH",
        "/api/library/file",
        params={"path": track},
        json={"artist": "B", "album": "New Album"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "changed": True}
    # cache entry reflects the new tags
    cached = main_module._lib_scan_cache["files"][0]
    assert cached["artist"] == "B"
    assert cached["album"] == "New Album"


def test_tag_write_failure_reports_500(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    (root / "albums").mkdir(parents=True)
    track = str(root / "albums" / "A - T.mp3")
    Path(track).write_bytes(b"x")
    entries = [{"path": track, "artist": "A", "album": "Album", "title": "T"}]
    _stub_tags(monkeypatch, entries, write_ok=False)
    monkeypatch.setenv("ARCHIVE_PATH", str(root))

    resp = client(
        "PATCH",
        "/api/library/file",
        params={"path": track},
        json={"artist": "B"},
    )
    assert resp.status_code == 500
    assert "tag write failed" in resp.json()["error"]


def test_tag_write_unknown_path_is_404(client, monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHIVE_PATH", str(tmp_path / "crate"))
    assert client("PATCH", "/api/library/file", params={"path": "nope.mp3"}, json={}).status_code == 404


def test_move_outside_crate_is_400(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    (root / "albums").mkdir(parents=True)
    src = root / "albums" / "inside.mp3"
    src.write_bytes(b"x")
    outside = str(tmp_path / "escape.mp3")  # absolute, outside the crate
    monkeypatch.setenv("ARCHIVE_PATH", str(root))

    # source exists inside the crate; destination absolute-outside -> 400
    assert client("POST", "/api/library/move", params={"src": str(src), "dst": outside}).status_code == 400


def test_move_success_patches_cache_path(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    (root / "albums").mkdir(parents=True)
    src = root / "albums" / "old.mp3"
    src.write_bytes(b"x")
    dst = str(root / "albums" / "new.mp3")
    entries = [{"path": str(src), "artist": "A", "title": "T"}]
    _stub_tags(monkeypatch, entries)
    _seed_cache(entries)
    monkeypatch.setenv("ARCHIVE_PATH", str(root))

    resp = client("POST", "/api/library/move", params={"src": str(src), "dst": dst})
    assert resp.status_code == 200
    assert resp.json()["actual"] == dst
    cached = main_module._lib_scan_cache["files"][0]
    assert cached["path"] == dst
