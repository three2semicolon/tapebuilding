"""Comprehensive functional sanity tests for tapebuilding packages."""

import pathlib
import subprocess
from unittest import mock

def test_config_defaults():
    from tapebuilding.core import config
    assert config.DEFAULT_FORMAT == "mp3"
    assert config.DEFAULT_BITRATE == "320k"
    assert config.VERBOSE is False

def test_downloader_import_and_mock_run():
    from tapebuilding.downloader import download
    # Ensure function exists
    assert callable(download)
    # Mock subprocess.run to avoid external calls
    mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with mock.patch("subprocess.run", return_value=mock_result) as m:
        result = download(["http://example.com/track.mp3"], pathlib.Path("out"), verbose=False)
    assert isinstance(result, list)
    # subprocess.run should have been called
    assert m.called

def test_exporter_writes(tmp_path):
    from tapebuilding.exporter import write_csv, write_manifest
    rows = [{"artist": "Test", "title": "Song", "spotify_url": "https://open.spotify.com/track/123"}]
    csv_path = tmp_path / "out.csv"
    write_csv(csv_path, rows, ["artist", "title"])
    assert "Test" in csv_path.read_text()
    manifest_path = tmp_path / "out.txt"
    write_manifest(manifest_path, rows)
    assert "https://" in manifest_path.read_text()

def test_retry_module_loads():
    from tapebuilding import retry
    assert hasattr(retry, "filter_existing")

def test_pipeline_instantiation():
    from tapebuilding.pipeline import Pipeline
    pline = Pipeline()
    assert hasattr(pline, "steps")
    assert callable(pline.add_step)