"""Utility helpers for tapebuilding."""

import subprocess
import sys
from pathlib import Path

def run_command(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a command and return CompletedProcess."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

def resolve_source(path: str) -> Path:
    """Resolve a source path relative to the project root."""
    return Path(path).expanduser().resolve()