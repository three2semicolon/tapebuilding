"""Tests for lib.catalog.indexer - TEST_PLANS.md 'lib/catalog/indexer.py'
section.

Written against the actual current source. No skeleton existed for this
module yet, so this is built fresh from TEST_PLANS.md's spec. Uses the
make_tagged_file fixture from tests/lib/conftest.py (inherited into this
subdirectory) to build a small real fixture crate rather than mocking
lib.tags.read_tags().

get_index()'s caching behavior is the highest-value coverage here per
TEST_PLANS.md - "stale-cache bugs are the classic failure mode" - so those
tests assert both on content (does a cache hit pick up a change it should,
and skip a rebuild when nothing changed?) and on the sidecar's own mtime
(does a rebuild actually touch it, does an unchanged-crate hit leave it
alone?), plus a direct assertion that build_index() itself is/isn't called,
not just that the observable output looks right either way.

NOTE: get_index() used to trust an existing sidecar unconditionally unless
--reindex was passed - see BUGFIX_PLAN.md's Bug 1 for the real-library
symptom that caused (~300 tracks silently missing from unmatched.csv
resolution because the cache was never invalidated after new downloads).
It now does a cheap stat-only mtime check (_is_stale()) before trusting the
cache, so a file added or removed from the crate is picked up on the next
call without needing --reindex. The tests below assert the current
(fixed) behavior, not the original one.
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

    def test_skips_duplicates_and_unorganized_dirs_at_top_level_only(self, tmp_path, make_tagged_file):
        # Bug 12: top-level "duplicates" and "unorganized" dirs should never be scanned
        make_tagged_file(filename="duplicates/should_be_skipped.mp3", title="Skipped Dup")
        make_tagged_file(filename="unorganized/should_be_skipped.mp3", title="Skipped Unorg")
        # a legitimately-named directory nested deeper is not the same thing and should still be indexed
        make_tagged_file(filename="Artist/duplicates/track.mp3", title="Kept Dup")
        make_tagged_file(filename="Artist/unorganized/track.mp3", title="Kept Unorg")

        titles = {e["title"] for e in build_index(str(tmp_path))}
        assert "Skipped Dup" not in titles
        assert "Skipped Unorg" not in titles
        assert "Kept Dup" in titles
        assert "Kept Unorg" in titles

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

    def test_cache_hit_auto_rebuilds_when_a_file_is_added(self, tmp_path, make_tagged_file):
        """Was test_cache_hit_does_not_pick_up_a_file_added_after_indexing,
        asserting the opposite (len == 1, 'stale on purpose'). That was the
        pre-fix behavior - get_index() trusted the sidecar unconditionally
        unless --reindex was passed. See BUGFIX_PLAN.md's Bug 1: that gap is
        exactly what let ~300 real tracks sit invisible in unmatched.csv.
        get_index() now auto-detects the change via a cheap mtime check and
        rebuilds without needing --reindex - this is the regression test for
        that fix."""
        make_tagged_file(filename="Artist/Album/Track.mp3", title="Track")
        exports = tmp_path / "exports"
        exports.mkdir()
        get_index(library_root=str(tmp_path), exports_dir_value=str(exports))

        time.sleep(0.01)  # ensure the new file's mtime strictly exceeds the sidecar's
        make_tagged_file(filename="Artist/Album/Track Two.mp3", title="Track Two")
        index = get_index(library_root=str(tmp_path), exports_dir_value=str(exports))
        assert len(index) == 2  # auto-invalidated, no --reindex needed

    def test_auto_invalidation_calls_build_index_when_crate_changed(
        self, tmp_path, make_tagged_file, monkeypatch
    ):
        """Direct complement to test_cache_hit_does_not_call_build_index_again:
        confirms the rebuild is actually triggered (not just that the
        eventual output happens to contain 2 entries some other way)."""
        import lib.catalog.indexer as indexer_module

        make_tagged_file(filename="Artist/Album/Track.mp3", title="Track")
        exports = tmp_path / "exports"
        exports.mkdir()
        get_index(library_root=str(tmp_path), exports_dir_value=str(exports))

        time.sleep(0.01)
        make_tagged_file(filename="Artist/Album/Track Two.mp3", title="Track Two")

        real_build_index = indexer_module.build_index
        calls = []
        monkeypatch.setattr(
            indexer_module, "build_index",
            lambda *a, **k: calls.append(1) or real_build_index(*a, **k)
        )
        get_index(library_root=str(tmp_path), exports_dir_value=str(exports))
        assert calls == [1]

    def test_cache_hit_auto_rebuilds_when_a_file_is_deleted(self, tmp_path, make_tagged_file):
        """Deletion leaves no mtime of its own to compare, but it does bump
        the containing directory's mtime - _newest_mtime() stats directories
        as well as files specifically to catch this case."""
        make_tagged_file(filename="Artist/Album/Track.mp3", title="Track")
        two = make_tagged_file(filename="Artist/Album/Track Two.mp3", title="Track Two")
        exports = tmp_path / "exports"
        exports.mkdir()
        get_index(library_root=str(tmp_path), exports_dir_value=str(exports))

        time.sleep(0.01)
        os.remove(two)
        index = get_index(library_root=str(tmp_path), exports_dir_value=str(exports))
        assert len(index) == 1  # auto-invalidated on deletion too

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
