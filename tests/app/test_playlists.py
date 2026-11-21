"""Behavioral tests for the playlist endpoints (app/main.py).

PLAYLISTS_PATH is pointed at a temp dir so nothing touches the real crate.
The new /api/playlists (create) endpoint takes a JSON body, matching what the
playlists.html frontend sends - the old POST /api/playlist read path/query
params and never matched the frontend's call.
"""

import os
from urllib.parse import quote


def test_list_playlists_empty(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    resp = client("GET", "/api/playlists")
    assert resp.status_code == 200
    assert resp.json() == {"playlists": []}


def test_create_playlist(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "my playlist.m3u8"
    resp = client("POST", "/api/playlists", json={"path": name, "entries": []})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # the file was written into the playlists dir
    assert (tmp_path / name).is_file()

    # and it shows up in the listing
    listed = client("GET", "/api/playlists").json()["playlists"]
    assert [p["name"] for p in listed] == [name]


def test_create_then_read_playlist(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "tracks.m3u8"
    client("POST", "/api/playlists", json={"path": name, "entries": []})

    got = client("GET", "/api/playlist", params={"path": str(tmp_path / name)})
    assert got.status_code == 200
    assert got.json()["existing"] == []


def test_rename_playlist(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "old.m3u8"
    client("POST", "/api/playlists", json={"path": name, "entries": []})

    resp = client("PATCH", f"/api/playlists/{name}", json={"new_name": "new.m3u8"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "new.m3u8"

    listed = client("GET", "/api/playlists").json()["playlists"]
    assert [p["name"] for p in listed] == ["new.m3u8"]
    assert not (tmp_path / name).exists()
    assert (tmp_path / "new.m3u8").exists()


def test_update_playlist_tracks(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "tracks.m3u8"
    client("POST", "/api/playlists", json={"path": name, "entries": []})

    one = tmp_path / "one.mp3"
    two = tmp_path / "two.mp3"
    entries = [{"path": str(one)}, {"path": str(two)}]
    resp = client(
        "POST", f"/api/playlists/{name}/tracks", json=entries
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    got = client("GET", "/api/playlist", params={"path": str(tmp_path / name)})
    assert got.status_code == 200
    assert got.json()["missing"] == ["one.mp3", "two.mp3"]


def test_delete_playlist(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "gone.m3u8"
    client("POST", "/api/playlists", json={"path": name, "entries": []})

    assert client("DELETE", f"/api/playlists/{name}").status_code == 200
    assert client("DELETE", f"/api/playlists/{name}").status_code == 404

    listed = client("GET", "/api/playlists").json()["playlists"]
    assert listed == []


def test_create_playlist_requires_body(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    resp = client("POST", "/api/playlists", json={})
    assert resp.status_code == 422


def test_playlists_listing_includes_cover_field(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    # a playlist with no cover -> cover is None
    client("POST", "/api/playlists", json={"path": "no-cover.m3u8", "entries": []})
    # a playlist with a cover jpg next to it -> cover url is set
    (tmp_path / "with-cover.m3u8").write_bytes(b"#EXTM3U\n")
    (tmp_path / "with-cover.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    listed = client("GET", "/api/playlists").json()["playlists"]
    by_name = {p["name"]: p for p in listed}
    assert by_name["no-cover.m3u8"]["cover"] is None
    assert by_name["with-cover.m3u8"]["cover"] == "/api/playlists/with-cover.m3u8/cover"


def test_playlist_cover_returns_204_when_no_cover(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    client("POST", "/api/playlists", json={"path": "no-cover.m3u8", "entries": []})
    resp = client("GET", "/api/playlists/no-cover.m3u8/cover")
    assert resp.status_code == 204


def test_playlist_cover_returns_200_when_cover_exists(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    (tmp_path / "with-cover.m3u8").write_bytes(b"#EXTM3U\n")
    (tmp_path / "with-cover.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    resp = client("GET", "/api/playlists/with-cover.m3u8/cover")
    assert resp.status_code == 200
    assert resp.content == b"\xff\xd8\xff\xe0fake-jpeg"
    assert resp.headers["content-type"].startswith("image/")


def test_tracks_playlists_membership(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    t1 = tmp_path / "track1.mp3"
    t2 = tmp_path / "track2.mp3"
    t3 = tmp_path / "track3.mp3"
    t1.write_bytes(b"fake audio")
    t2.write_bytes(b"fake audio")
    t3.write_bytes(b"fake audio")
    (tmp_path / "a.m3u8").write_text("#EXTM3U\ntrack1.mp3\ntrack2.mp3\n", encoding="utf-8")
    (tmp_path / "b.m3u8").write_text("#EXTM3U\ntrack2.mp3\ntrack3.mp3\n", encoding="utf-8")
    resp = client(
        "POST",
        "/api/tracks/playlists",
        json={"paths": [str(t1), str(t2), str(tmp_path / "track4.mp3")]},
    )
    assert resp.status_code == 200
    membership = resp.json()["playlists"]
    assert membership[str(t1)] == ["a.m3u8"]
    assert set(membership[str(t2)]) == {"a.m3u8", "b.m3u8"}
    assert membership[str(tmp_path / "track4.mp3")] == []


def test_single_track_playlists_endpoint(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    t1 = tmp_path / "track1.mp3"
    t1.write_bytes(b"fake audio")
    (tmp_path / "a.m3u8").write_text("#EXTM3U\ntrack1.mp3\n", encoding="utf-8")
    resp = client("GET", f"/api/tracks/{quote(str(t1))}/playlists")
    assert resp.status_code == 200
    assert resp.json()["playlists"] == ["a.m3u8"]


def test_playlist_cover_traversal_does_not_escape(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    (tmp_path / "a.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
    # a secret file sitting outside the playlists dir
    escape = tmp_path.parent / "secret.jpg"
    escape.write_bytes(b"top-secret")
    # traversal via the cover name must not leak the outside file:
    # multi-segment traversal never matches the route (404), and a handler-level
    # name is confined to the playlists dir (204 when no cover).
    resp = client("GET", "/api/playlists/../../secret.jpg/cover")
    assert resp.status_code in (204, 404)
    assert escape.read_bytes() == b"top-secret"


def test_delete_playlist_traversal_does_not_delete_outside_file(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    (tmp_path / "keep.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
    escape = tmp_path.parent / "escape.txt"
    escape.write_bytes(b"secret")
    assert client("DELETE", "/api/playlists/../../escape.txt").status_code == 404
    assert escape.read_bytes() == b"secret"
    # the in-crate playlist is untouched
    listed = client("GET", "/api/playlists").json()["playlists"]
    assert [p["name"] for p in listed] == ["keep.m3u8"]


def test_rename_playlist_rejects_traversal_target(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    (tmp_path / "old.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
    resp = client(
        "PATCH", "/api/playlists/old.m3u8", json={"new_name": "../../escape.m3u8"}
    )
    assert resp.status_code == 400
    assert not (tmp_path.parent / "escape.m3u8").exists()
    assert (tmp_path / "old.m3u8").exists()


# ---------------------------------------------------------------- Phase 3: enhanced listing

def test_listing_enhanced_kind_source_count_duration_edited(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))

    # synced playlist with source header + one track (file exists)
    (tmp_path / "albums").mkdir()
    (tmp_path / "albums" / "song.mp3").write_bytes(b"fake audio")
    (tmp_path / "synced.m3u8").write_text(
        "#EXTM3U\n#TAPEDECK-SOURCE:spotify:abc123\n"
        "#EXTINF:203,Artist - Title\nalbums/song.mp3\n",
        encoding="utf-8",
    )
    # local playlist, empty
    client("POST", "/api/playlists", json={"path": "local.m3u8", "entries": []})

    listed = client("GET", "/api/playlists").json()["playlists"]
    by_name = {p["name"]: p for p in listed}

    synced = by_name["synced.m3u8"]
    assert synced["kind"] == "synced"
    assert synced["source_id"] == "spotify:abc123"
    assert synced["count"] == 1
    assert synced["duration"] == 203.0
    assert synced["edited"] is False

    local = by_name["local.m3u8"]
    assert local["kind"] == "local"
    assert local["source_id"] is None
    assert local["count"] == 0
    assert local["duration"] == 0.0
    assert local["edited"] is False


# ---------------------------------------------------------------- Phase 3: full playlist read

def test_full_read_entries_ghosts_duration(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))

    (tmp_path / "albums").mkdir()
    (tmp_path / "albums" / "existing.mp3").write_bytes(b"fake audio")

    name = "tracks.m3u8"
    (tmp_path / name).write_text(
        "#EXTM3U\n"
        "#EXTINF:203,Artist - Title\n"
        "albums/existing.mp3\n"
        "#EXTINF:150,Missing - Song\n"
        "albums/missing.mp3\n",
        encoding="utf-8",
    )

    resp = client("GET", f"/api/playlists/{name}")
    assert resp.status_code == 200
    j = resp.json()
    assert j["name"] == name
    assert "etag" in j
    assert j["kind"] == "local"
    assert j["source_id"] is None
    assert len(j["entries"]) == 1
    assert j["entries"][0]["exists"] is True
    assert j["entries"][0]["artist"] == "Artist"
    assert j["entries"][0]["title"] == "Title"
    assert len(j["ghosts"]) == 1
    assert j["ghosts"][0]["exists"] is False
    assert j["ghosts"][0]["artist"] == "Missing"
    assert j["ghosts"][0]["title"] == "Song"
    assert j["duration"] == 353.0


def test_full_read_etag_mismatch(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "tracks.m3u8"
    (tmp_path / name).write_text("#EXTM3U\n#EXTINF:100,A - T\nalbums/a.mp3\n", encoding="utf-8")

    # wrong etag -> 409
    resp = client("GET", f"/api/playlists/{name}", headers={"If-Match": "wrong_etag"})
    assert resp.status_code == 409

    # correct etag -> 200
    resp = client("GET", f"/api/playlists/{name}")
    etag = resp.json()["etag"]
    resp = client("GET", f"/api/playlists/{name}", headers={"If-Match": etag})
    assert resp.status_code == 200


# ---------------------------------------------------------------- Phase 3: ops

def test_ops_add(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    monkeypatch.setenv("ARCHIVE_PATH", str(tmp_path))

    name = "tracks.m3u8"
    (tmp_path / name).write_text("#EXTM3U\n", encoding="utf-8")

    # create a track file inside the crate
    track = tmp_path / "albums" / "song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"fake audio")

    resp = client("POST", f"/api/playlists/{name}/ops", json={
        "ops": [{"op": "add", "paths": [str(track)]}]
    })
    assert resp.status_code == 200
    j = resp.json()
    assert "etag" in j
    assert j["ops"][0]["op"] == "add"
    assert j["ops"][0]["added"] == 1

    # verify the entry was added
    resp = client("GET", f"/api/playlists/{name}")
    assert resp.status_code == 200
    j = resp.json()
    assert len(j["entries"]) == 1


def test_ops_remove(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "tracks.m3u8"
    (tmp_path / "albums").mkdir()
    for fn in ("a.mp3", "b.mp3", "c.mp3"):
        (tmp_path / "albums" / fn).write_bytes(b"fake audio")
    (tmp_path / name).write_text(
        "#EXTM3U\n#EXTINF:100,A - T1\nalbums/a.mp3\n"
        "#EXTINF:200,B - T2\nalbums/b.mp3\n"
        "#EXTINF:300,C - T3\nalbums/c.mp3\n",
        encoding="utf-8",
    )

    resp = client("POST", f"/api/playlists/{name}/ops", json={
        "ops": [{"op": "remove", "ids": [0, 2]}]
    })
    assert resp.status_code == 200
    j = resp.json()
    assert j["ops"][0]["removed"] == 2

    resp = client("GET", f"/api/playlists/{name}")
    assert resp.status_code == 200
    j = resp.json()
    assert len(j["entries"]) == 1
    assert j["entries"][0]["title"] == "T2"


def test_ops_move(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "tracks.m3u8"
    (tmp_path / "albums").mkdir()
    for fn in ("a.mp3", "b.mp3", "c.mp3"):
        (tmp_path / "albums" / fn).write_bytes(b"fake audio")
    (tmp_path / name).write_text(
        "#EXTM3U\n#EXTINF:100,A - T1\nalbums/a.mp3\n"
        "#EXTINF:200,B - T2\nalbums/b.mp3\n"
        "#EXTINF:300,C - T3\nalbums/c.mp3\n",
        encoding="utf-8",
    )

    # move entry at index 0 to position 2
    resp = client("POST", f"/api/playlists/{name}/ops", json={
        "ops": [{"op": "move", "ids": [0], "to": 2}]
    })
    assert resp.status_code == 200

    resp = client("GET", f"/api/playlists/{name}")
    assert resp.status_code == 200
    j = resp.json()
    assert [e["title"] for e in j["entries"]] == ["T2", "T3", "T1"]


def test_ops_etag_mismatch(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "tracks.m3u8"
    (tmp_path / name).write_text("#EXTM3U\n", encoding="utf-8")

    resp = client("POST", f"/api/playlists/{name}/ops", json={
        "etag": "wrong_etag",
        "ops": [{"op": "add", "paths": []}]
    })
    assert resp.status_code == 409


# ---------------------------------------------------------------- Phase 3: undo

def test_undo_after_ops(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    monkeypatch.setenv("ARCHIVE_PATH", str(tmp_path))
    name = "tracks.m3u8"
    (tmp_path / name).write_text("#EXTM3U\n", encoding="utf-8")

    track = tmp_path / "song.mp3"
    track.write_bytes(b"fake audio")

    # add a track
    client("POST", f"/api/playlists/{name}/ops", json={
        "ops": [{"op": "add", "paths": [str(track)]}]
    })

    # verify it's there
    resp = client("GET", f"/api/playlists/{name}")
    assert len(resp.json()["entries"]) == 1

    # undo
    resp = client("POST", f"/api/playlists/{name}/undo")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # verify it's gone
    resp = client("GET", f"/api/playlists/{name}")
    assert len(resp.json()["entries"]) == 0


def test_undo_nothing(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "no_snaps.m3u8"
    (tmp_path / name).write_text("#EXTM3U\n", encoding="utf-8")

    resp = client("POST", f"/api/playlists/{name}/undo")
    assert resp.status_code == 409


# ---------------------------------------------------------------- Phase 3: detach

def test_detach(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "synced.m3u8"
    (tmp_path / name).write_text(
        "#EXTM3U\n#TAPEDECK-SOURCE:spotify:abc123\n#EXTINF:100,A - T\nalbums/a.mp3\n",
        encoding="utf-8",
    )

    resp = client("POST", f"/api/playlists/{name}/detach")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "detached"
    assert resp.json()["source_id"] == "spotify:abc123"

    # verify the headers persisted
    resp = client("GET", f"/api/playlists/{name}")
    assert resp.json()["kind"] == "detached"
    assert resp.json()["source_id"] == "spotify:abc123"


def test_detach_already_detached(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "detached.m3u8"
    (tmp_path / name).write_text(
        "#EXTM3U\n#TAPEDECK-SOURCE:local\n#TAPEDECK-DETACHED:spotify:abc123\n",
        encoding="utf-8",
    )

    resp = client("POST", f"/api/playlists/{name}/detach")
    assert resp.status_code == 400


def test_detach_not_synced(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "local.m3u8"
    (tmp_path / name).write_text("#EXTM3U\n#TAPEDECK-SOURCE:local\n", encoding="utf-8")

    resp = client("POST", f"/api/playlists/{name}/detach")
    assert resp.status_code == 400


# ---------------------------------------------------------------- Phase 3: reattach

def test_reattach_merge(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "detached.m3u8"
    (tmp_path / name).write_text(
        "#EXTM3U\n#TAPEDECK-SOURCE:local\n#TAPEDECK-DETACHED:spotify:abc123\n"
        "#EXTINF:100,Local - Track\nalbums/local.mp3\n",
        encoding="utf-8",
    )

    import app.routers.playlists as pl_module
    monkeypatch.setattr(pl_module, "build_playlists", lambda **kw: {"written": 1})
    monkeypatch.setattr(pl_module, "get_index", lambda *a, **k: [])
    monkeypatch.setattr(pl_module, "plan_playlist", lambda *a, **k: ([], []))

    resp = client("POST", f"/api/playlists/{name}/reattach", json={"mode": "merge"})
    assert resp.status_code == 200
    assert resp.json()["kind"] == "synced"

    # verify DETACHED header is gone, playlist is synced again
    resp = client("GET", f"/api/playlists/{name}")
    assert resp.json()["kind"] == "synced"
    assert resp.json()["source_id"] == "spotify:abc123"


def test_reattach_replace(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "detached.m3u8"
    (tmp_path / name).write_text(
        "#EXTM3U\n#TAPEDECK-SOURCE:local\n#TAPEDECK-DETACHED:spotify:abc123\n"
        "#EXTINF:100,Local - Track\nalbums/local.mp3\n",
        encoding="utf-8",
    )

    import app.routers.playlists as pl_module
    monkeypatch.setattr(pl_module, "build_playlists", lambda **kw: {"written": 1})
    monkeypatch.setattr(pl_module, "get_index", lambda *a, **k: [])
    monkeypatch.setattr(pl_module, "plan_playlist", lambda *a, **k: ([], []))

    resp = client("POST", f"/api/playlists/{name}/reattach", json={"mode": "replace"})
    assert resp.status_code == 200


def test_reattach_invalid_mode(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "detached.m3u8"
    (tmp_path / name).write_text(
        "#EXTM3U\n#TAPEDECK-SOURCE:local\n#TAPEDECK-DETACHED:spotify:abc123\n",
        encoding="utf-8",
    )

    resp = client("POST", f"/api/playlists/{name}/reattach", json={"mode": "invalid"})
    assert resp.status_code == 400


def test_reattach_not_detached(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "local.m3u8"
    (tmp_path / name).write_text("#EXTM3U\n#TAPEDECK-SOURCE:local\n", encoding="utf-8")

    resp = client("POST", f"/api/playlists/{name}/reattach", json={"mode": "merge"})
    assert resp.status_code == 400


# ---------------------------------------------------------------- Phase 3: delete + undo

def test_delete_to_history(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "gone.m3u8"
    client("POST", "/api/playlists", json={"path": name, "entries": []})

    resp = client("DELETE", f"/api/playlists/{name}")
    assert resp.status_code == 200
    assert "history" in resp.json()

    # file moved to .history
    assert not (tmp_path / name).exists()
    hdir = tmp_path / ".history"
    assert hdir.is_dir()
    hist_files = list(hdir.iterdir())
    assert len(hist_files) == 1
    assert hist_files[0].name.endswith("_" + name)

    # listing doesn't include it
    listed = client("GET", "/api/playlists").json()["playlists"]
    assert listed == []


def test_undo_after_delete(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "gone.m3u8"
    (tmp_path / name).write_text("#EXTM3U\n#EXTINF:100,A - T\nalbums/a.mp3\n", encoding="utf-8")

    client("DELETE", f"/api/playlists/{name}")
    assert not (tmp_path / name).exists()

    resp = client("POST", f"/api/playlists/{name}/undo")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # file restored
    assert (tmp_path / name).exists()


# ---------------------------------------------------------------- Phase 3: relink

def test_relink(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    monkeypatch.setenv("ARCHIVE_PATH", str(tmp_path))
    name = "tracks.m3u8"
    # playlist with a ghost entry (file doesn't exist at the recorded path)
    (tmp_path / name).write_text(
        "#EXTM3U\n"
        "#EXTINF:203,Artist - Title\n"
        "albums/missing.mp3\n",
        encoding="utf-8",
    )
    # the actual file exists at the same relative path
    actual = tmp_path / "albums" / "missing.mp3"
    actual.parent.mkdir(parents=True)
    actual.write_bytes(b"fake audio")

    import app.routers.playlists as pl_module
    fake_index = [{
        "path": str(actual),
        "artist": "Artist",
        "title": "Title",
        "album": "Album",
        "track": 1,
        "disc": 0,
        "year": 2000,
        "length": 203.0,
    }]
    monkeypatch.setattr(pl_module, "get_index", lambda *a, **k: fake_index)

    resp = client("POST", f"/api/playlists/{name}/relink")
    assert resp.status_code == 200
    j = resp.json()
    assert "relocated" in j
    assert "ambiguous" in j
    assert "missing" in j


# ---------------------------------------------------------------- Phase 3: refresh / rebuild

def test_refresh(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "synced.m3u8"
    (tmp_path / name).write_text(
        "#EXTM3U\n#TAPEDECK-SOURCE:spotify:abc123\n",
        encoding="utf-8",
    )

    import app.routers.playlists as pl_module
    monkeypatch.setattr(pl_module, "build_playlists", lambda **kw: {"written": 1, "skipped": 0})

    resp = client("POST", f"/api/playlists/{name}/refresh")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["kind"] == "synced"
    assert resp.json()["source_id"] == "spotify:abc123"


def test_refresh_not_synced(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "local.m3u8"
    (tmp_path / name).write_text("#EXTM3U\n#TAPEDECK-SOURCE:local\n", encoding="utf-8")

    resp = client("POST", f"/api/playlists/{name}/refresh")
    assert resp.status_code == 400


def test_rebuild(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    name = "synced.m3u8"
    (tmp_path / name).write_text(
        "#EXTM3U\n#TAPEDECK-SOURCE:spotify:abc123\n",
        encoding="utf-8",
    )

    import app.routers.playlists as pl_module
    monkeypatch.setattr(pl_module, "build_playlists", lambda **kw: {"written": 1})

    resp = client("POST", f"/api/playlists/{name}/rebuild")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------- Phase 3: sync preview

def test_sync_preview(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    (tmp_path / "synced.m3u8").write_text(
        "#EXTM3U\n#TAPEDECK-SOURCE:spotify:abc123\n#EXTINF:100,A - T\nalbums/a.mp3\n",
        encoding="utf-8",
    )

    import app.routers.playlists as pl_module
    monkeypatch.setattr(pl_module, "get_index", lambda *a, **k: [])
    monkeypatch.setattr(pl_module, "plan_playlist", lambda *a, **k: ([], []))

    resp = client("GET", "/api/sync/preview")
    assert resp.status_code == 200
    j = resp.json()
    assert "playlists" in j


# ---------------------------------------------------------------- Phase 3: links

def test_links_api(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYLISTS_PATH", str(tmp_path))
    monkeypatch.setenv("ARCHIVE_PATH", str(tmp_path))

    track = tmp_path / "song.mp3"
    track.write_bytes(b"fake audio")

    resp = client("POST", "/api/links", json={
        "url": "https://open.spotify.com/track/abc123",
        "path": str(track),
        "artist": "Artist",
        "title": "Title",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
