"""Command-line interface for tapebuilding."""

import argparse
import sys
from typing import List, Optional

from tapebuilding.pipeline import Pipeline

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tapebuilding")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--apply", action="store_true", help="Actually perform actions")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--only", dest="only", choices=["download", "import", "playlist"], help="Run only specific step")
    return parser

def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Placeholder for pipeline steps
    pipeline = Pipeline()
    # Example step registration (not functional yet)
    # pipeline.add_step("download", lambda ctx: download([], Path("")))
    # pipeline.add_step("import", lambda ctx: import_drop(...))
    # pipeline.add_step("playlist", lambda ctx: ...)

    if args.dry_run:
        print("Dry run selected – no changes will be made.")
    if args.apply:
        print("Apply selected – actions will be performed.")
    print("CLI skeleton ready – implement steps as needed.")

if __name__ == "__main__":
    main()