"""Tests for download.retry - TEST_PLANS.md 'download/retry.py' section.

SECOND-HIGHEST PRIORITY module in the suite: entirely rebuilt from a
README description this session, no prior implementation to diff
against, and its only bug so far (missing `import re`) was found by
inspection, not by running it. Written against the actual current
source.
"""
import csv
import os

import pytest

from download.retry import (
    read_failure_log,
    collect_failures,
    write_retry_list,
    write_report_csv,
    run_retry,
)


class TestReadFailureLog:
    def test_parses_url_with_reason(self, tmp_path):
        log = tmp_path / "failed.txt"
        log.write_text("https://a  # track_unavailable\n", encoding="utf-8")
        result = read_failure_log(str(log))
        assert result == {"https://a": {"track_unavailable"}}

    def test_parses_bare_url_with_empty_reason_set(self, tmp_path):
        log = tmp_path / "failed.txt"
        log.write_text("https://a\n", encoding="utf-8")
        result = read_failure_log(str(log))
        assert result == {"https://a": set()}

    def test_ignores_blank_lines(self, tmp_path):
        log = tmp_path / "failed.txt"
        log.write_text("https://a\n\n\nhttps://b\n", encoding="utf-8")
        result = read_failure_log(str(log))
        assert set(result.keys()) == {"https://a", "https://b"}

    def test_missing_file_returns_empty_dict(self, tmp_path):
        result = read_failure_log(str(tmp_path / "does_not_exist.txt"))
        assert result == {}

    def test_preserves_insertion_order(self, tmp_path):
        log = tmp_path / "failed.txt"
        log.write_text("https://z\nhttps://a\nhttps://m\n", encoding="utf-8")
        result = read_failure_log(str(log))
        assert list(result.keys()) == ["https://z", "https://a", "https://m"]


class TestCollectFailures:
    def test_unions_reasons_for_url_appearing_in_both_files(self, tmp_path):
        failed = tmp_path / "failed.txt"
        soft = tmp_path / "soft.txt"
        failed.write_text("https://a  # track_unavailable\n", encoding="utf-8")
        soft.write_text("https://a  # LookupError\n", encoding="utf-8")

        result = collect_failures(str(failed), str(soft))
        assert result["https://a"] == {"track_unavailable", "LookupError"}

    def test_merges_distinct_urls_across_both_files(self, tmp_path):
        failed = tmp_path / "failed.txt"
        soft = tmp_path / "soft.txt"
        failed.write_text("https://a\n", encoding="utf-8")
        soft.write_text("https://b\n", encoding="utf-8")

        result = collect_failures(str(failed), str(soft))
        assert set(result.keys()) == {"https://a", "https://b"}


class TestRunRetryHardExclusion:
    def _write_logs(self, tmp_path, failed_lines, soft_lines=""):
        failed = tmp_path / "failed_downloads.txt"
        soft = tmp_path / "soft_failures.txt"
        failed.write_text(failed_lines, encoding="utf-8")
        soft.write_text(soft_lines, encoding="utf-8")
        return str(failed), str(soft)

    def test_hard_failure_excluded_by_default(self, tmp_path):
        failed_path, soft_path = self._write_logs(
            tmp_path, "https://gone  # track_unavailable\n"
        )
        result = run_retry(
            failed_path=failed_path, soft_path=soft_path,
            output_path=str(tmp_path / "retry_list.txt"),
            no_check=True,
        )
        assert result["hard_excluded"] == ["https://gone"]
        assert result["retry_urls"] == []

    def test_include_unavailable_keeps_hard_failures(self, tmp_path):
        failed_path, soft_path = self._write_logs(
            tmp_path, "https://gone  # track_unavailable\n"
        )
        result = run_retry(
            failed_path=failed_path, soft_path=soft_path,
            output_path=str(tmp_path / "retry_list.txt"),
            no_check=True, include_unavailable=True,
        )
        assert result["hard_excluded"] == []
        assert "https://gone" in result["retry_urls"]


class TestRunRetryNoCheck:
    def test_no_check_skips_library_recheck_entirely(self, tmp_path):
        failed_path, soft_path = tmp_path / "failed.txt", tmp_path / "soft.txt"
        failed_path.write_text("https://a\nhttps://b\n", encoding="utf-8")
        soft_path.write_text("", encoding="utf-8")

        result = run_retry(
            failed_path=str(failed_path), soft_path=str(soft_path),
            output_path=str(tmp_path / "retry_list.txt"),
            no_check=True,
        )
        assert set(result["retry_urls"]) == {"https://a", "https://b"}
        assert result["already_on_disk"] == []


class TestRunRetryLibraryRecheckConsistency:
    """The real regression test per TEST_PLANS.md: run_retry()'s recheck
    path has to agree with spotify_download.py's own --pre-skip-existing
    path on which urls are 'already on disk', since they're supposed to
    use the identical predict-then-normalize-then-check-index sequence.
    """

    def test_agrees_with_spotify_download_pre_skip_existing(self, tmp_path, sample_manifest_csv, fixture_library, monkeypatch):
        from download.spotify_download import _check_existing
        from download.manifest import read_csv_metadata

        failed_path = tmp_path / "failed.txt"
        soft_path = tmp_path / "soft.txt"
        # both urls from sample_manifest_csv "failed" at some point
        failed_path.write_text(
            "https://open.spotify.com/track/AAA  # LookupError\n"
            "https://open.spotify.com/track/BBB  # LookupError\n",
            encoding="utf-8",
        )
        soft_path.write_text("", encoding="utf-8")

        retry_result = run_retry(
            failed_path=str(failed_path), soft_path=str(soft_path),
            output_path=str(tmp_path / "retry_list.txt"),
            metadata_source=str(sample_manifest_csv),
            library_root=str(fixture_library),
        )

        metadata = read_csv_metadata(str(sample_manifest_csv))
        urls = list(metadata.keys())
        existing, new, no_meta, library_root, library_index = _check_existing(
            urls, metadata, str(fixture_library), "mp3"
        )

        # AAA matches fixture_library's pre-seeded file - both paths should
        # agree it's "already on disk" and therefore NOT in retry_urls.
        assert "https://open.spotify.com/track/AAA" in retry_result["already_on_disk"]
        assert "https://open.spotify.com/track/AAA" not in retry_result["retry_urls"]
        assert "https://open.spotify.com/track/BBB" in retry_result["retry_urls"]


class TestRunRetryNoMeta:
    def test_url_with_no_metadata_is_kept_not_dropped(self, tmp_path, monkeypatch):
        failed_path = tmp_path / "failed.txt"
        soft_path = tmp_path / "soft.txt"
        failed_path.write_text("https://unknown-track\n", encoding="utf-8")
        soft_path.write_text("", encoding="utf-8")

        empty_export_dir = tmp_path / "exports"
        empty_export_dir.mkdir()

        result = run_retry(
            failed_path=str(failed_path), soft_path=str(soft_path),
            output_path=str(tmp_path / "retry_list.txt"),
            metadata_source=str(empty_export_dir),
            library_root=str(tmp_path / "empty_library"),
        )
        assert "https://unknown-track" in result["no_meta"]
        assert "https://unknown-track" in result["retry_urls"]


class TestRunRetryReportCsv:
    def test_report_csv_sorted_by_artist_album_track(self, tmp_path):
        failed_path = tmp_path / "failed.txt"
        soft_path = tmp_path / "soft.txt"
        failed_path.write_text(
            "https://z  # LookupError\n"
            "https://a  # LookupError\n",
            encoding="utf-8",
        )
        soft_path.write_text("", encoding="utf-8")

        metadata_csv = tmp_path / "manifest.csv"
        metadata_csv.write_text(
            "spotify_url,artist_names,track_name,album_name\n"
            "https://z,Zebra Artist,Z Track,Z Album\n"
            "https://a,Aardvark Artist,A Track,A Album\n",
            encoding="utf-8",
        )

        result = run_retry(
            failed_path=str(failed_path), soft_path=str(soft_path),
            output_path=str(tmp_path / "retry_list.txt"),
            metadata_source=str(metadata_csv),
            library_root=str(tmp_path / "empty_library"),
            report_csv_path=str(tmp_path / "report.csv"),
        )

        rows = result["report_rows"]
        artists_in_order = [r["artist"] for r in rows]
        assert artists_in_order == sorted(artists_in_order, key=str.lower)

    def test_report_csv_search_link_is_url_encoded(self, tmp_path):
        failed_path = tmp_path / "failed.txt"
        soft_path = tmp_path / "soft.txt"
        failed_path.write_text("https://x  # LookupError\n", encoding="utf-8")
        soft_path.write_text("", encoding="utf-8")

        metadata_csv = tmp_path / "manifest.csv"
        metadata_csv.write_text(
            "spotify_url,artist_names,track_name\n"
            "https://x,Some & Artist,Some Track\n",
            encoding="utf-8",
        )

        result = run_retry(
            failed_path=str(failed_path), soft_path=str(soft_path),
            output_path=str(tmp_path / "retry_list.txt"),
            metadata_source=str(metadata_csv),
            library_root=str(tmp_path / "empty_library"),
            report_csv_path=str(tmp_path / "report.csv"),
        )
        search_url = result["report_rows"][0]["search"]
        assert search_url.startswith("https://www.youtube.com/results?search_query=")
        assert " " not in search_url  # spaces must be percent-encoded
        query_part = search_url.split("search_query=", 1)[1]
        assert "&" not in query_part  # the artist's literal '&' must be percent-encoded, not raw

    def test_no_report_csv_path_means_no_file_written(self, tmp_path):
        failed_path = tmp_path / "failed.txt"
        soft_path = tmp_path / "soft.txt"
        failed_path.write_text("https://x\n", encoding="utf-8")
        soft_path.write_text("", encoding="utf-8")

        run_retry(
            failed_path=str(failed_path), soft_path=str(soft_path),
            output_path=str(tmp_path / "retry_list.txt"),
            no_check=True,
        )
        assert not (tmp_path / "retry_report.csv").exists()


class TestWriteRetryListAndReportCsv:
    def test_write_retry_list_one_url_per_line(self, tmp_path):
        out = tmp_path / "out.txt"
        write_retry_list(["https://a", "https://b"], str(out))
        assert out.read_text(encoding="utf-8") == "https://a\nhttps://b\n"

    def test_write_report_csv_header_and_rows(self, tmp_path):
        out = tmp_path / "report.csv"
        rows = [{"artist": "A", "track": "T", "album": "Al", "reason": "r", "spotify_url": "u", "search": "s"}]
        write_report_csv(rows, str(out))
        with out.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            read_rows = list(reader)
        assert read_rows == rows
