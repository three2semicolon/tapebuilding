"""organize.preimport - stage unorganized/ so the beets importer does the
right thing.

runs organize.cleanup's regrouping logic BEFORE beets, not after. the
two-pass importer (beets_import.py) splits albums into one folder per
track-artist and leaks whole albums into singles/ because (a) incoming
files carry no albumartist tag, so beets' default album path template
keys the folder on the per-track artist, which varies on collab/featured
tracks; and (b) album tracks dumped loose (not under an albums/ folder)
are skipped by the album pass and swept up as singletons by the singles
pass.

this pre-pass fixes both, straight off file tags (mediafile), independent
of beets:

  - scan every audio file under <input> (default <crate>/unorganized).
  - group by album tag. groups of >=2 files that share an album become one
    staged folder <input>/albums/<albumartist> - <album>/, with the canonical
    albumartist written into every file's tag - so beets' $albumartist template
    resolves to one value (one folder, no split) and the album pass sees a real
    folder (no singleton leak).
  - singletons (no album tag, or a lone track of an album we don't have) stay
    loose for the beets singles pass.
  - add to existing albums: if <crate>/albums already holds an album with the
    same (albumartist, album), route the incoming tracks INTO that folder and
    write the existing album's albumartist tag (keep the folder tag-consistent
    so a future as-is reimport won't re-split). merge matching is conservative -
    an incoming group only merges when exactly one existing folder matches the
    normalized (albumartist, album); ambiguous collisions stage a new folder
    instead of risking a wrong merge. merges are filesystem-only; beets.db is
    left stale on the merged tracks until you rebuild it
    (`uv run organize cleanup --rebuild-db`).

split into two modules, each ~170-200 lines instead of one ~400-line
file:

  - plan.py   - the read-only half: index_existing_albums(), build_plan(),
                and the naming/scanning helpers they use
  - apply.py  - the apply half: stage() (the entry point), the actual
                moves/quarantine/tag-writes, duplicates_dir(),
                prune_unorganized()

everything previously reachable as `organize.preimport.<name>` is
re-exported below unchanged, so beets_import.py's/cli.py's existing
`from organize.preimport import stage` doesn't need to change.

idempotent: re-running on an already-staged drop is a no-op (groups re-stage
to the same folders; already-correct tags aren't rewritten).

beets_import.py runs this automatically before its two passes, so the whole
flow is one command. run preimport standalone (via organize's cli) to
preview/stage without importing:

  uv run organize preimport                       # dry-run: print plan
  uv run organize preimport --apply                # stage + write tags
  uv run organize preimport --apply --verbose      # print every move
  uv run organize preimport --no-merge-existing    # new folders only
  uv run organize preimport -i /path -o /crate

toolkit imports come straight from lib.tags/lib.text (lib/ refactor) -
only group_files/is_unrelated_va_collision/resolve_crate stay
organize-package imports (from organize.cleanup), since those are
organize-specific policy, not generic lib/ concerns.
"""

from .apply import duplicates_dir, prune_unorganized, stage
from .plan import build_plan, index_existing_albums

__all__ = [
    'build_plan',
    'duplicates_dir',
    'index_existing_albums',
    'prune_unorganized',
    'stage',
]
