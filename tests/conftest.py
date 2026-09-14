"""Shared fixtures for tests under tests/lib/ (including tests/lib/catalog/).

make_tagged_file() builds a short, real, silent audio file via ffmpeg and
optionally tags it via mediafile - the same library lib.tags.read_tags()
uses under the hood - so tests exercise the real read path instead of a
hand-rolled fake. Requires ffmpeg to be resolvable (system PATH, or
FFMPEG_PATH per .env.example) and `mediafile` installed (pulled in by
beets, already a project dependency).
"""
import os
import shutil
import subprocess

import pytest
from dotenv import load_dotenv
from mediafile import MediaFile

from lib.paths import ffmpeg_path


def _ffmpeg_executable():
    configured = ffmpeg_path()
    if not configured:
        return "ffmpeg"
    if os.path.isdir(configured):
        exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        return os.path.join(configured, exe)
    return configured


@pytest.fixture
def make_tagged_file(tmp_path):
    """Factory fixture: make_tagged_file(filename=None, ext=".mp3", **tags).

    filename may include subdirectories (e.g. "albums/Artist/01 Track.mp3");
    parent directories are created automatically, relative to the test's
    tmp_path. Any keyword args are set as mediafile fields (artist,
    albumartist, album, title, track, ...) and saved. Returns the file's
    path as a string.
    """
    counter = {"n": 0}

    def _make(filename=None, ext=".mp3", **tags):
        counter["n"] += 1
        name = filename or f"track{counter['n']}{ext}"
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                _ffmpeg_executable(), "-y",
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
