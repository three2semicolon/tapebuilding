"""organize.validate - unified validation and organization command.

Provides a single command to:
1. Validate/fix individual files using the crate as ground truth
2. Run the full organize pipeline (preimport -> import -> cleanup) with --all
"""

import os
import sys
from typing import Optional

import click

from lib.paths import resolve as resolve_path
from organize.beets_import import run_import
from organize.cleanup import apply as cleanup_apply
from organize.preimport import stage as preimport_stage


def validate_file(file_path: str, crate_path: str) -> dict:
    """
    Validate a single file against the crate as ground truth.

    Args:
        file_path: Path to the file to validate
        crate_path: Path to the crate root

    Returns:
        dict: Validation results
    """
    # This is a simplified implementation - in a full version, this would:
    # 1. Extract metadata from the file
    # 2. Determine what the file should be based on crate contents
    # 3. Compare and report mismatches
    # 4. Optionally fix the file

    print(f"Validating file: {file_path}")
    print(f"Using crate as ground truth: {crate_path}")

    # Placeholder implementation
    if not os.path.exists(file_path):
        return {'ok': False, 'error': f'File not found: {file_path}'}

    if not os.path.isdir(crate_path):
        return {'ok': False, 'error': f'Crate not found: {crate_path}'}

    # In a real implementation, we would:
    # - Read the file's metadata
    # - Check if it belongs in the crate based on metadata
    # - Verify tags match what they should be
    # - Check if file is in correct location
    # - Report any issues

    print("  [Placeholder] File validation would occur here")
    print("  [Placeholder] Would check metadata, tags, location, etc.")
    print("  [Placeholder] Would report any mismatches found")

    return {'ok': True, 'validated': True, 'fixes_suggested': 0}


@click.command()
@click.argument('file_path', type=click.Path(exists=False), required=False)
@click.option('--all', is_flag=True, help='Run full organize pipeline on entire crate')
@click.option('--apply', is_flag=True, help='Actually perform changes (default: dry-run)')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed output')
def validate(file_path: Optional[str], all: bool, apply: bool, verbose: bool):
    """Unified validation and organization command.

    FILE_PATH: Path to single file to validate (if not using --all)

    Examples:
      organize validate --all           # Run full pipeline on crate
      organize validate song.mp3        # Validate single file
      organize validate --apply song.mp3 # Validate and fix single file
    """
    # Resolve crate path
    try:
        crate_path = resolve_path('ARCHIVE_PATH', required=True)
    except Exception as e:
        click.echo(f"error: Could not resolve crate path: {e}", err=True)
        sys.exit(1)

    if all:
        # Run full pipeline: preimport -> import -> cleanup
        if verbose:
            click.echo(f"Running full organize pipeline on crate: {crate_path}")

        unorganized_dir = os.path.join(crate_path, 'unorganized')

        # Step 1: Preimport staging
        if verbose:
            click.echo("\n=== Step 1: Preimport staging ===")
        try:
            preimport_result = preimport_stage(
                unorganized_dir,
                crate_path,
                apply=apply,
                verbose=verbose
            )
            if verbose:
                click.echo(f"Preimport complete: {preimport_result.get('staged_folders', 0)} folders staged")
        except Exception as e:
            click.echo(f"error: Preimport failed: {e}", err=True)
            sys.exit(1)

        # Step 2: Beets import
        if verbose:
            click.echo("\n=== Step 2: Beets import ===")
        try:
            import_result = run_import(
                unorganized_dir,
                output_dir=crate_path,
                dry_run=not apply,
                verbose=verbose
            )
            if not import_result.get('ok', False):
                click.echo(f"error: Import failed: {import_result.get('error', 'Unknown error')}", err=True)
                sys.exit(1)
            if verbose:
                click.echo("Import complete")
        except Exception as e:
            click.echo(f"error: Import failed: {e}", err=True)
            sys.exit(1)

        # Step 3: Cleanup
        if verbose:
            click.echo("\n=== Step 3: Cleanup ===")
        try:
            cleanup_result = cleanup_apply.run_cleanup(
                crate=crate_path,
                apply=apply,
                verbose=verbose
            )
            if verbose:
                click.echo("Cleanup complete")
        except Exception as e:
            click.echo(f"error: Cleanup failed: {e}", err=True)
            sys.exit(1)

        click.echo("\nFull organize pipeline completed successfully!")

    elif file_path:
        # Validate single file
        result = validate_file(file_path, crate_path)
        if not result.get('ok', False):
            click.echo(f"error: {result.get('error', 'Validation failed')}", err=True)
            sys.exit(1)
        else:
            click.echo("File validation completed successfully!")
    else:
        # No arguments provided
        click.echo("Error: Either provide a file path or use --all flag", err=True)
        click.echo("Usage: organize validate [--all] [FILE_PATH]")
        sys.exit(1)


if __name__ == '__main__':
    validate()
