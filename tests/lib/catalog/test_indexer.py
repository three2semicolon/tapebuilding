"""Tests for lib.catalog.indexer - TEST_PLANS.md 'lib/catalog/indexer.py'
section.

Written against the actual current source. No skeleton existed for this
module yet, so this is built fresh from TEST_PLANS.md's spec. Uses the
make_tagged_file fixture from tests/lib/conftest.py (inherited into this
subdirectory) to build a small real fixture crate rather than mocking
lib.tags.read_tags().

get_index()'s caching behavior is the highest-value coverage here per
TEST_PLANS.md - "stale-cache bugs are the classic failure mode" - so those
tests assert both on content (does a cache hit pick up a new file it
shouldn't?) and on the sidecar's own mtime (does a rebuild actually touch
it, does a cache hit leave it alone?).
"""
import os
import time

from lib.catalog.indexer import (
    build_index,
    save_index,
    load_index,
    get_index,
    index_path,
    INDEX_NAME,
)


class TestBuildIndex:
    def test_walks_and_reads_tags(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="Artist/Album/01 Track.mp3", title="Track One")
        make_tagged_file(filename="Artist/Album/02 Track.mp3", title="Track Two")
        (tmp_path / "Artist" / "Album" / "cover.jpg").write_bytes(b"not audio")

        index = build_index(str(tmp_path))
        titles = {e["title"] for e in index}
        assert titles == {"Track One", "Track Two"}

    def test_skips_playlists_dir_at_top_level_only(self, tmp_path, make_tagged_file):
        # a top-level "playlists" dir holds .m3u8/.csv, not audio - never scanned
        make_tagged_file(filename="playlists/should_be_skipped.mp3", title="Skipped")
        # a legitimately-named "playlists" *album* nested deeper is not the
        # same thing and should still be indexed
        make_tagged_file(filename="Artist/playlists/track.mp3", title="Kept")

        titles = {e["title"] for e in build_index(str(tmp_path))}
        assert "Skipped" not in titles
        assert "Kept" in titles

    def test_empty_root_returns_empty_list(self, tmp_path):
        assert build_index(str(tmp_path)) == []


class TestIndexPath:
    def test_joins_exports_dir_and_index_name(self):
        assert index_path("/some/exports") == os.path.join("/some/exports", INDEX_NAME)


class TestSaveAndLoadIndex:
    def test_round_trips(self, tmp_path):
        index = [{"title": "A", "artist": "B", "path": "/x.mp3"}]
        sidecar = tmp_path / "index.jsonl"
        save_index(index, str(sidecar))
        assert load_index(str(sidecar)) == index

    def test_save_is_atomic_no_tmp_file_left_behind(self, tmp_path):
        sidecar = tmp_path / "index.jsonl"
        save_index([{"a": 1}], str(sidecar))
        assert sidecar.exists()
        assert not (tmp_path / "index.jsonl.tmp").exists()

    def test_load_missing_file_returns_none(self, tmp_path):
        assert load_index(str(tmp_path / "nope.jsonl")) is None

    def test_load_corrupt_file_returns_none(self, tmp_path):
        bad = tmp_path / "corrupt.jsonl"
        bad.write_text("{not valid json\n")
        assert load_index(str(bad)) is None


class TestGetIndex:
    def test_builds_and_writes_sidecar_on_first_call(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="Artist/Album/Track.mp3", title="Track")
        exports = tmp_path / "exports"
        exports.mkdir()

        index = get_index(library_root=str(tmp_path), exports_dir_value=str(exports))
        assert len(index) == 1
        assert (exports / INDEX_NAME).exists()

    def test_cache_hit_does_not_pick_up_a_file_added_after_indexing(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="Artist/Album/Track.mp3", title="Track")
        exports = tmp_path / "exports"
        exports.mkdir()
        get_index(library_root=str(tmp_path), exports_dir_value=str(exports))

        make_tagged_file(filename="Artist/Album/Track Two.mp3", title="Track Two")
        index = get_index(library_root=str(tmp_path), exports_dir_value=str(exports))
        assert len(index) == 1  # stale on purpose - this is the cache-hit path

    def test_reindex_forces_rebuild_and_picks_up_new_file(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="Artist/Album/Track.mp3", title="Track")
        exports = tmp_path / "exports"
        exports.mkdir()
        get_index(library_root=str(tmp_path), exports_dir_value=str(exports))

        make_tagged_file(filename="Artist/Album/Track Two.mp3", title="Track Two")
        index = get_index(
            library_root=str(tmp_path), exports_dir_value=str(exports), reindex=True
        )
        assert len(index) == 2

    def test_cache_hit_does_not_touch_sidecar_mtime(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="Artist/Album/Track.mp3", title="Track")
        exports = tmp_path / "exports"
        exports.mkdir()
        get_index(library_root=str(tmp_path), exports_dir_value=str(exports))
        sidecar = exports / INDEX_NAME
        mtime_before = sidecar.stat().st_mtime_ns

        get_index(library_root=str(tmp_path), exports_dir_value=str(exports))
        assert sidecar.stat().st_mtime_ns == mtime_before

    def test_cache_hit_does_not_call_build_index_again(self, tmp_path, make_tagged_file, monkeypatch):
        """Matches the original skeleton's explicit ask: assert build_index()
        itself is skipped on a cache hit, not just that its effects look
        stale - a future change that re-walks the crate but happens to
        write back identical content would pass the content/mtime checks
        above while still failing this one."""
        import lib.catalog.indexer as indexer_module

        make_tagged_file(filename="Artist/Album/Track.mp3", title="Track")
        exports = tmp_path / "exports"
        exports.mkdir()
        get_index(library_root=str(tmp_path), exports_dir_value=str(exports))  # first call builds + caches

        calls = []
        monkeypatch.setattr(
            indexer_module, "build_index",
            lambda *a, **k: calls.append(1) or []
        )
        get_index(library_root=str(tmp_path), exports_dir_value=str(exports))
        assert calls == []

    def test_reindex_updates_sidecar_mtime(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="Artist/Album/Track.mp3", title="Track")
        exports = tmp_path / "exports"
        exports.mkdir()
        get_index(library_root=str(tmp_path), exports_dir_value=str(exports))
        sidecar = exports / INDEX_NAME
        mtime_before = sidecar.stat().st_mtime_ns
        time.sleep(0.01)

        get_index(library_root=str(tmp_path), exports_dir_value=str(exports), reindex=True)
        assert sidecar.stat().st_mtime_ns > mtime_before

    def test_missing_sidecar_triggers_rebuild_even_without_reindex_flag(self, tmp_path, make_tagged_file):
        make_tagged_file(filename="Artist/Album/Track.mp3", title="Track")
        exports = tmp_path / "exports"
        exports.mkdir()
        # no prior call, no sidecar on disk yet - should build fresh, not
        # error or return an empty/None result
        index = get_index(library_root=str(tmp_path), exports_dir_value=str(exports))
        assert len(index) == 1
