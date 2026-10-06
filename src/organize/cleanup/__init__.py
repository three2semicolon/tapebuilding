"""organize.cleanup - reorganize the beets crate into proper albums and
singles.

repairs the two things the beets two-pass importer gets wrong on this
library:
  1. albums split into multiple folders, one per track-artist, because
     beets keyed the album folder on $artist (per-track) instead of
     $albumartist and the source files had no albumartist tag (beets
     fell back to the track artist, which varies on collab/featured
     tracks).
  2. whole albums scattered as singletons in singles/, because pass 2
     imports every track standalone (no album grouping).

split into three modules, each ~150-270 lines instead of one ~600-line
file, along the actual seams in what the code does:

  - common.py       - resolve_crate(), used by both passes below
  - grouping.py      - the forward-looking regroup pass: group_files(),
                        build_plan(), the VA-collision helpers
  - apply.py           - the regular pass's apply half: run_cleanup(),
                        plus prune_empty_dirs()/rebuild_db()/
                        config_path()

everything that was previously reachable as `organize.cleanup.<name>`
is re-exported below unchanged, so cli.py's and preimport.py's existing
`from organize.cleanup import ...` calls don't need to change.

the regrouper works straight off file tags (mediafile), independent of
beets - see grouping.py's docstring for the grouping rules. The regular
cleanup pass now also handles previously wrongly-merged folders that
previously required a separate repair pass. idempotent: re-running
`organize cleanup` on an already-clean crate is a no-op.

cli.py owns argument parsing / exit codes; run_cleanup()
below is the plain, import-safe entry point cli.py (and anything
else) calls into.

usage (via organize's cli):
  uv run organize cleanup                        # dry-run: print plan, move nothing
  uv run organize cleanup --apply                # move files + write albumartist tags
  uv run organize cleanup --apply --rebuild-db   # ...then rebuild beets.db from the reorganized crate
  uv run organize cleanup --verbose              # print every planned move
  uv run organize cleanup --crate /path/to/crate
"""

from .common import resolve_crate
from .grouping import (
    build_plan,
    group_files,
    is_unrelated_va_collision,
    shares_artist_token,
)
from .apply import check_tags, config_path, prune_empty_dirs, rebuild_db, run_cleanup

__all__ = [
    'resolve_crate',
    'build_plan',
    'group_files',
    'is_unrelated_va_collision',
    'shares_artist_token',
    'check_tags',
    'config_path',
    'prune_empty_dirs',
    'rebuild_db',
    'run_cleanup',
]
