"""Tests for serving crate audio over http (/files/...) and the playable
url the library endpoint attaches to each track - the bits that let another
program (e.g. a discord bot on the same lan) play crate tracks directly."""

from unittest.mock import patch

from urllib.parse import quote

import app.main as main_module
from app.routers import library as library_module


def _write_track(root, rel, content=b"id3 fake mp3 bytes"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def test_serve_crate_audio(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    track = _write_track(root, "albums/The Band/01 - The Band - Track One.mp3")
    monkeypatch.setenv("ARCHIVE_PATH", str(root))

    resp = client("GET", f"/files/{quote('albums/The Band/01 - The Band - Track One.mp3')}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/mpeg")
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.content == track.read_bytes()


def test_serve_flac_and_ogg(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    flac = _write_track(root, "singles/Lone - Single.flac", b"fLaC")
    ogg = _write_track(root, "singles/Lone - Single.ogg", b"OGGS")
    monkeypatch.setenv("ARCHIVE_PATH", str(root))

    assert client("GET", "/files/singles/Lone%20-%20Single.flac").headers["content-type"].startswith("audio/")
    assert client("GET", "/files/singles/Lone%20-%20Single.ogg").headers["content-type"].startswith("audio/")


def test_serve_supports_range_requests(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    _write_track(root, "singles/Lone - Single.mp3", b"0123456789")
    monkeypatch.setenv("ARCHIVE_PATH", str(root))

    resp = client("GET", "/files/singles/Lone%20-%20Single.mp3", headers={"Range": "bytes=0-3"})
    assert resp.status_code == 206
    assert resp.content == b"0123"


def test_serve_missing_file_is_404(client, monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHIVE_PATH", str(tmp_path / "crate"))
    assert client("GET", "/files/albums/nope.mp3").status_code == 404
    assert client("GET", "/files/").status_code == 404


def test_serve_path_traversal_is_404(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    (root / "albums").mkdir(parents=True)
    _write_track(root, "albums/inside.mp3")
    outside = tmp_path / "escape.txt"
    outside.write_bytes(b"secret")
    monkeypatch.setenv("ARCHIVE_PATH", str(root))

    assert client("GET", "/files/../escape.txt").status_code == 404
    assert client("GET", "/files/albums/../../escape.txt").status_code == 404


def test_serve_non_audio_is_404(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    _write_track(root, "readme.txt", b"not audio")
    monkeypatch.setenv("ARCHIVE_PATH", str(root))

    assert client("GET", "/files/readme.txt").status_code == 404


def _library_files(client, monkeypatch, tmp_path, fake):
    """run a library query; the index loads synchronously via refresh_index,
    so one request is enough (no polling). mocks refresh_index so no real
    tag reads or sidecar writes happen."""
    root = tmp_path / "crate"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHIVE_PATH", str(root))
    stats = {"scanned": len(fake), "read": len(fake), "skipped": 0, "removed": 0, "total": len(fake)}
    # reset the shared LibraryIndex singleton so this test's data is loaded fresh
    library_module._lib_index._state = "idle"
    library_module._lib_index._rows = []
    library_module._lib_index._by_path = {}
    with patch("app.services.library_index._refresh_index", return_value=(fake, stats)):
        resp = client("GET", "/api/library")
    assert resp.status_code == 200
    j = resp.json()
    assert not j.get("scanning"), j
    assert not j.get("error"), j
    return j["rows"]


def test_library_includes_playable_url(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    track = _write_track(root, "albums/A/01 - A - T.mp3")
    fake = [{
        "path": str(track),
        "artist": "A",
        "albumartist": "",
        "album": "Album",
        "title": "T",
        "track": 1,
        "disc": 0,
        "year": 2000,
        "length": 3.5,
    }]
    rows = _library_files(client, monkeypatch, tmp_path, fake)
    assert len(rows) == 1
    f = rows[0]
    assert f["path"] == str(track)
    assert f["url"] == "/files/albums/A/01%20-%20A%20-%20T.mp3"


def test_library_url_points_at_served_file(client, monkeypatch, tmp_path):
    root = tmp_path / "crate"
    track = _write_track(root, "albums/B/02 - B - U.mp3")
    fake = [{
        "path": str(track), "artist": "B", "albumartist": "", "album": "Album",
        "title": "U", "track": 2, "disc": 0, "year": 0, "length": 0.0,
    }]
    url = _library_files(client, monkeypatch, tmp_path, fake)[0]["url"]
    resp = client("GET", url)
    assert resp.status_code == 200
    assert resp.content == track.read_bytes()
