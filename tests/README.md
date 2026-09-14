# tests/

Structure mirrors `src/`: one test file per module, grouped into
subdirectories per package (`tests/lib/`, `tests/download/`, etc.), plus
two cross-cutting files at the top level (`conftest.py`,
`test_imports.py`). See `TEST_PLANS.md` at the repo root for the
rationale behind what's tested and in what priority order.

## Status of each file

**Real tests, written against actual source:**
- `test_imports.py` — import + `--help` smoke tests for every module and CLI command
- `lib/test_paths.py`, `test_text.py`, `test_tags.py`, `test_m3u.py`, `catalog/test_indexer.py`, `catalog/test_matcher.py`
- `download/test_manifest.py`, `test_existing.py`, `test_ytdl.py`, `test_spotify_download.py`, `test_retry.py`, `test_spotify_export.py`
- `organize/test_preimport.py`, `test_beets_import.py`, `test_cleanup.py`
- `playlists/test_build.py` — includes one real `xfail`: `_select_playlists()`'s
  default scope compares `playlists.csv`'s `owner` (a display name) directly
  against `SPOTIFY_USER_ID` (a user id), so "my playlists only" never
  matches its own playlists. Flips to a normal passing test the moment
  that's fixed — see the test's docstring in the file itself.
- `tapedeck/test_resolve.py`, `test_copy.py`, `test_deck.py` — includes one
  pinned quirk, not a bug fix: `copy.py`'s `unstage()` prunes empty
  directories with a single bottom-up `os.walk`, so a parent that only
  becomes empty *because* its own child was just removed in the same pass
  isn't re-checked and survives until a later unload's prune pass finishes
  it off. `test_unstage_prunes_empty_parent_directories` asserts that
  exact two-call behavior rather than the (wrong) assumption that one
  `unstage()` call fully collapses an empty subtree. **These three were
  validated against the real `resolve.py`/`copy.py`/`deck.py` source using
  a hand-built stand-in for `lib/` (only `tapedeck/` and the top-level docs
  were shared, not `lib/` itself), so double-check they still pass as-is
  against your actual `lib/` before trusting them beyond that.**
- `core/test_download_songs.py`, `test_sync.py` — both modules now have
  real tests implemented (no longer skeletons)

All seven packages (`lib/`, `download/`, `organize/`, `playlists/`,
`tapedeck/`, `core/`) are now fully real — every skeleton has been replaced
with actual test implementations. `playlists/` carries the one known `xfail`
above (not a skeleton), and `core/` tests are fully implemented.

Some tests currently fail due to ongoing development work, but the test
files themselves are real and document the intended behavior.

## conftest.py files

- `tests/conftest.py` — root-level, cross-cutting.
- `tests/lib/conftest.py` — `make_tagged_file`, a real-audio-file factory
  fixture (ffmpeg + mediafile), inherited by `tests/lib/catalog/` too.
- `tests/download/conftest.py` — `sample_manifest_csv` / `fixture_library`,
  the paired CSV + pre-seeded-library fixtures `test_retry.py` and
  `test_spotify_download.py` use for their `--pre-skip-existing` /
  library-recheck-consistency tests. **This one was reconstructed from
  how those two files use the fixtures, not from an original** — it
  didn't exist yet even though the tests that depend on it were already
  marked real. Double-check its shape (the exact CSV columns and the
  pre-seeded filename) matches what you actually intended before relying
  on it for anything beyond what's already covered.

## Running

```bash
uv run pytest tests/
```

Run just the smoke tests first (cheapest, catches import-time bugs
before anything else):

```bash
uv run pytest tests/test_imports.py -v
```

Skip the still-skeleton files and see only real coverage:

```bash
uv run pytest tests/ -v -m "not skip"
```

(That last one won't actually filter `@pytest.mark.skip` — skipped
tests always show as skipped, not excluded. Use `--no-skip` reporting
or just read the skip reasons in the `-v` output; they all start with
`"<module> source not yet reviewed"` so they're easy to grep for.)

## Adding a new test file

New module → new test file in the matching subdirectory, named
`test_<module>.py`. Add it to `test_imports.py`'s `MODULES` list (and
`SUBCOMMANDS`/`CONSOLE_SCRIPTS` if it's a new CLI command) before
writing anything else — see `NEW_FEATURE_GUIDE.md` §5.
