"""Import + CLI smoke tests - TEST_PLANS.md section 0.

Deliberately dumb tests: import every module the project ships, and
invoke every console-script command/subcommand with --help. Nothing here
checks behavior - it exists purely to catch the class of bug found
during post-refactor testing (a function documented as existing but
never actually written, or a missing import), which is an import-time
failure that costs nothing to catch and a full manual `uv run` cycle to
find by hand.

If you add a new module or a new CLI subcommand, add it here first,
before writing any behavioral test for it.
"""
import importlib

import pytest
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Bare module imports
# ---------------------------------------------------------------------------

MODULES = [
    # lib/
    "lib.paths",
    "lib.text",
    "lib.tags",
    "lib.m3u",
    "lib.spotify_auth",
    "lib.catalog.indexer",
    "lib.catalog.matcher",
    # download/
    "download.cli",
    "download.spotify_export",
    "download.spotify_api",
    "download.spotify_download",
    "download.existing",
    "download.manifest",
    "download.ytdl",
    "download.retry",
    "download.soundbyte",
    # organize/
    "organize.cli",
    "organize.cleanup",
    "organize.preimport",
    "organize.beets_import",
    "organize.normalize_artists",
    # playlists/
    "playlists.cli",
    "playlists.build",
    # tapedeck/
    "tapedeck.cli",
    "tapedeck.resolve",
    "tapedeck.copy",
    "tapedeck.deck",
    # core/
    "core.cli",
    "core.download_songs",
    "core.sync",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports_cleanly(module_name):
    importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# Console-script entry points, exercised the way a user actually invokes
# them (through Click), not just via bare import.
# ---------------------------------------------------------------------------

def _cli_object(dotted_path):
    module_name, attr = dotted_path.split(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


# mirrors pyproject.toml's [project.scripts] exactly - keep these in sync
CONSOLE_SCRIPTS = {
    "download": "download.cli:download",
    "organize": "organize.cli:organize",
    "playlists": "playlists.cli:playlists",
    "tapedeck": "tapedeck.cli:tapedeck",
    "core": "core.cli:core",
}

# subcommands per group, from README.md's documented usage. playlists has
# none - it's a single click.command, not a click.group.
SUBCOMMANDS = {
    "download": ["export", "spotify", "ytdl", "retry", "soundbyte"],
    "organize": ["import", "cleanup"],
    "tapedeck": ["load", "unload", "list"],
    "core": ["download-songs", "sync"],
}


@pytest.mark.parametrize("script_name,dotted_path", CONSOLE_SCRIPTS.items())
def test_console_script_help(script_name, dotted_path):
    runner = CliRunner()
    cli_obj = _cli_object(dotted_path)
    result = runner.invoke(cli_obj, ["--help"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "script_name,subcommand",
    [(s, sub) for s, subs in SUBCOMMANDS.items() for sub in subs],
)
def test_subcommand_help(script_name, subcommand):
    runner = CliRunner()
    cli_obj = _cli_object(CONSOLE_SCRIPTS[script_name])
    result = runner.invoke(cli_obj, [subcommand, "--help"])
    assert result.exit_code == 0, result.output
