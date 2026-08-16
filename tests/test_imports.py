"""Basic import sanity checks for the tapebuilding package."""

import pytest

def test_imports():
    # Core modules
    from tapebuilding.core import config, logger
    from tapebuilding.downloader import download
    from tapebuilding.exporter import write_csv, write_manifest
    from tapebuilding.retry import filter_existing
    from tapebuilding.pipeline import Pipeline
    from tapebuilding.importer import import_drop
    from tapebuilding.cli import main as cli_main

    # Ensure they are importable without error
    assert config is not None
    assert logger is not None
    assert download is not None
    assert write_csv is not None
    assert write_manifest is not None
    assert import_drop is not None
    assert Pipeline is not None
    assert cli_main is not None