"""organize.cleanup.common - crate-resolution helper shared across the
cleanup subpackage.

split out on its own (instead of living in apply.py or grouping.py)
because both apply.py's run_cleanup() and resplit.py's run_resplit()
need it, and apply.py imports from grouping.py - putting it in either
of those would make resplit.py import a module it has nothing else to
do with, or risk a future circular import if grouping.py ever needs
crate resolution too.
"""

from lib.paths import resolve as resolve_path


def resolve_crate(cli_value=None):
    """crate root from --crate, else ARCHIVE_PATH - required, no expanduser
    fallback. deliberately stricter than lib.paths.archive_path()'s default
    (~/music/tapebuilding): this command moves files and rewrites tags, so
    silently landing on a guessed path instead of erroring is the wrong
    failure mode here. same reasoning applies to organize.beets_import's
    crate resolution."""
    return resolve_path('ARCHIVE_PATH', cli_value, required=True)
