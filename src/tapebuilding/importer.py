"""Beets import wrapper."""

import subprocess
import sys
from pathlib import Path
from typing import Optional

def import_drop(
    drop: Path,
    crate: Path,
    *,
    verbose: bool = False,
    reindex: bool = False,
    dry_run: bool = False,
) -> None:
    """Import new files from drop into crate using beets import."""
    cmd = ["uv", "run", "beets", "import", str(drop)]
    if reindex:
        cmd.extend(["--reindex"])
    if dry_run:
        cmd.append("--dry-run")
    if not verbose:
        cmd.extend(["-q"])
    result = subprocess.run(cmd, cwd=str(crate), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error during import: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    if verbose:
        print(result.stdout)