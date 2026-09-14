"""Shared fixtures for tests under tests/organize/.

make_tagged_file() is identical to tests/lib/conftest.py's fixture of the
same name - duplicated here because pytest fixtures aren't inherited
across sibling test directories (tests/organize/ isn't a subdirectory of
tests/lib/). organize.preimport.stage() and organize.cleanup.run_cleanup()
both make real filesystem decisions off real mediafile tags, same
reasoning as tests/lib/ - a hand-rolled fake tag dict wouldn't exercise
the actual read/write path.

Consider promoting this fixture to tests/conftest.py (the root conftest)
if you want a single copy shared by every subdirectory instead of two
near-identical fixture files.
"""
import subprocess

import pytest
from mediafile import MediaFile


@pytest.fixture
def make_tagged_file(tmp_path):
    """Factory fixture: make_tagged_file(filename=None, ext=".mp3", **tags).

    filename may include subdirectories (e.g. "crate/albums/Artist - Album/
    01 Track.mp3"); parent directories are created automatically, relative
    to the test's tmp_path. Any keyword args are set as mediafile fields
    (artist, albumartist, album, title, track, ...) and saved. Returns the
    file's path as a string.
    """
    counter = {"n": 0}

    def _make(filename=None, ext=".mp3", **tags):
        counter["n"] += 1
        name = filename or f"track{counter['n']}{ext}"
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                "-t", "1",
                "-codec:a", "libmp3lame", "-q:a", "9",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        if tags:
            m = MediaFile(str(path))
            for field, value in tags.items():
                setattr(m, field, value)
            m.save()
        return str(path)

    return _make
