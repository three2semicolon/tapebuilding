# tapebuilding — todo

The `pipelines/` → `core/` refactor (`lib/` foundation + per-package
`cli.py` split + in-process `core/`) is complete. See `PACKAGE_OVERVIEW.md`
for current state and `README.md` for usage. What's left is genuinely
unscheduled work, not a checklist to execute in order.

**Current status note:** Bug 1's implementation and regression coverage are
complete. Bug 2's forward fix and resplit implementation are present and
smoke-tested; the missing `sanitize` import in `resplit.py` flagged below is
now fixed (confirmed against the current source), and a real resplit run
against the live crate has cleaned up the pre-existing wrong merges — the
real organize regression tests are still the outstanding piece there. Album-
name normalization (merge-on-ingest half) is now implemented — see that
section below. What's left across both is genuinely unscheduled work, not a
checklist to execute in order.

---

## Fixes — planned (found this planning session, not yet implemented)

Two matching/organization bugs surfaced from real playlist syncs, plus
one enhancement they motivate. Full root-cause analysis and fix plan in
`BUGFIX_PLAN.md` (new) — the summary below isn't enough to implement
from directly; that file lists the exact source files and a verification
script needed to confirm each hypothesis before touching code.

- [X] **Multi-artist tracks land in `unmatched.csv` despite already
  being in the crate**, then get reimported into beets' duplicates
  folder. **Root cause confirmed, fix implemented and tested.**
  `lib.text.split_artists()` was never the problem (third revision, not
  the original separator hypothesis). The real bug was
  `lib.catalog.indexer.get_index()` trusting `.playlist_index.jsonl`
  unconditionally — confirmed by running `playlists --apply --rescrape --reindex`, which recovered "I Admit with Isaiah Kaleo" plus ~300
  other tracks that had silently accumulated across un-reindexed
  `download spotify` sessions. `get_index()` now does a cheap stat-only
  mtime check (`_is_stale()`) before trusting the cache, and rebuilds
  automatically when the crate has changed — tested against add/
  no-change/delete cases with stub modules, all three behave correctly.
  `--reindex` still works as a manual override. Full detail in
  `BUGFIX_PLAN.md` §Bug 1.

  - [X] Regression test added:
    `tests/lib/catalog/test_indexer.py` now covers the add/delete/
    unchanged-crate cases against the real fixed `get_index()`, plus a
    direct assertion that `build_index()` is/isn't actually called
    (not just that the output happens to look right). One pre-existing
    test in that file had been asserting the old buggy behavior as
    correct (`len(index) == 1` after adding a file) — fixed to assert
    the corrected behavior, with a docstring note on why.
  - [X] `PACKAGE_OVERVIEW.md`'s `lib/catalog/indexer.py` description
    updated to describe `_is_stale()`/`_newest_mtime()` auto-invalidation,
    the fail-safe direction in each case, and the Bug 1 fix it closes,
    per `NEW_FEATURE_GUIDE.md` §5.4.
- [X] **Unrelated same-titled singles by different artists merged into
  one album folder** (e.g. two different artists' singles both titled
  "Automatic" ending up in one `Automatic/` folder) — **fixed and
  smoke-tested**. `organize.cleanup.group_files()` still buckets by
  album title first, but `build_plan()` (both `cleanup.py`'s and
  `preimport.py`'s) now calls the new `is_unrelated_va_collision()`
  right after `canonical_albumartist()` resolves a group: an exactly-
  two-track group that only came out `'Various Artists'` because the
  two members share zero artist tokens, and neither file's own
  `albumartist` tag actually says VA, gets filed as two singletons
  instead of merged. Verified against a standalone stub-module script
  (same pattern `BUGFIX_PLAN.md`'s Bug 1 fix used) with three cases: the
  real `Anysia Kym`/`Spencer.` "Automatic" collision (now splits), a
  genuine shared-artist-token album (still merges), and an explicitly
  VA-tagged compilation (still merges) — all three pass. See
  `BUGFIX_PLAN.md` §Bug 2.

  - [ ] Regression test still owed: the standalone script above needs
    turning into a real `tests/organize/test_cleanup.py` /
    `test_preimport.py` case per `NEW_FEATURE_GUIDE.md` §5.2/5.3 — same
    "still needs wiring into the actual suite" gap Bug 1's fix had
    before it was closed out.
  - [ ] `organize cleanup`'s resplit mode (see the item below) is still
    needed to fix folders that were already wrongly merged *before*
    this fix landed — this only stops *new* bad merges.
- [X] **`organize cleanup` needs a resplit mode** to repair
  already-wrongly-merged folders once the grouping-key fix above lands
  — **implemented, smoke-tested, and now wired up end-to-end.**
  `plan_resplit()`/`run_resplit()` (opt-in and separate from the
  regular `--apply` pass — a normal `cleanup --apply` run can't undo
  the historical damage on its own: an already-wrongly-merged folder
  now carries a self-inflicted `'Various Artists'` albumartist tag that
  looks like a genuine compilation signal to the forward-looking check,
  so resplit recomputes each folder's grouping from the untouched raw
  `artist` tag instead) are wired to `organize cleanup --resplit` /
  `--resplit --apply` on the CLI (`--resplit` + `--rebuild-db` errors
  loudly rather than silently ignoring one, same convention as
  `--all`+`--mine`). Dry-run by default, `--apply` to actually move
  files, matching every other command's convention; doesn't rebuild
  `beets.db` or the crate catalog itself, prints a reminder to run
  `cleanup --rebuild-db` + a playlists/tapedeck reindex afterward.
  `README.md`'s `organize cleanup` section documents both usage lines.
  Verified against a real (temp-dir) filesystem: a poisoned
  `Various Artists - Automatic` folder splits into two singles and the
  old folder is removed; a genuine multi-track album with chained
  artist overlap (varying featured collaborators per track, like the
  real Ash Levi album) is correctly left untouched.

  - [ ] Regression test still owed (same gap as Bug 2's grouping-key
    fix above) — the filesystem smoke test used to verify this should
    become a real `tests/organize/test_cleanup.py` case.
  - [X] **Resplit runtime bug, fixed:** `resplit.py` calls `sanitize()`
    when constructing destination names — confirmed the current source
    imports it (`from lib.tags import safe_move, write_tag, sanitize`).
    A real resplit run against the live crate has since cleaned up the
    pre-existing wrong merges.
  - [ ] **Resplit destination collision:** `_name_album_component()`
    currently turns an already-existing canonical destination into
    `Name (2)`, `Name (3)`, etc. This can create duplicate album folders
    when a split component actually belongs with an existing album folder.
    Change resplit planning/apply behavior to recognize an existing
    compatible canonical album destination and merge into it rather than
    inventing `(2)`; retain numeric suffixes only for genuinely distinct
    collisions that cannot safely be merged.
  - [ ] `PACKAGE_OVERVIEW.md`'s `organize/` section still needs updating
    to describe the new `organize/cleanup/` and `organize/preimport/`
    subpackage layout (see the split note below) and the `--resplit`
    flag, per `NEW_FEATURE_GUIDE.md` §5.4 — not done yet.
  - [ ] note from a session:
    * **Fix resplit destination artist determination.** Each artist-separated component must derive its folder artist from the component itself, not from the old merged folder's `albumartist`.
    * For `ABC - ABC` + `BCA - ABC`, produce `ABC - ABC` and `BCA - ABC`.
    * If the component represents a single track/release that belongs under `singles`, use the existing single-placement logic rather than creating an album folder.
    * Numeric `(2)` suffixes should **not** be used to resolve this particular situation; they should only be a last-resort safeguard for genuinely ambiguous same-artist/same-album collisions.
- [X] **Split `cleanup.py` and `preimport.py`** — both had grown past a
  comfortable single-file size (~610 and ~400 lines) and were becoming
  two different concerns stacked in one file each. Split into
  subpackages, each new module landing in the ~150-270 line range,
  along the seams the code already had rather than arbitrary cuts:

  - `organize/cleanup/` — `common.py` (`resolve_crate()`, shared by the
    other three), `grouping.py` (the forward-looking regroup pass:
    `group_files()`/`build_plan()`/the VA-collision helpers),
    `resplit_plan.py` (resplit's read-only planning half:
    `plan_resplit()`), `resplit.py` (resplit's apply half:
    `run_resplit()`), `apply.py` (the regular pass's apply half:
    `run_cleanup()` + `prune_empty_dirs()`/`rebuild_db()`/
    `config_path()`).
  - `organize/preimport/` — `plan.py` (`index_existing_albums()`/
    `build_plan()` + the naming/scanning helpers), `apply.py`
    (`stage()`, `duplicates_dir()`, `prune_unorganized()`, the actual
    moves/tag-writes).
  - every previously-public name (`organize.cleanup.run_cleanup`,
    `.run_resplit`, `.group_files`, etc.; `organize.preimport.stage`,
    etc.) is re-exported from each package's `__init__.py` unchanged,
    so `cli.py` and cross-imports between the two packages didn't need
    any changes.
  - verified by actually importing both packages (against stubbed
    `lib.paths`/`lib.tags`/`lib.text`) and running `run_cleanup()`,
    `run_resplit()`, and `stage()` end-to-end against fixture data,
    including a real temp-dir filesystem pass for `run_resplit()` and
    `index_existing_albums()` — not just an import smoke test, per
    `NEW_FEATURE_GUIDE.md` §5's "actually run it" rule. One bug caught
    this way and fixed: `config_path()` needed a second `dirname()`
    call after moving one directory deeper (`config.yaml` sits in
    `organize/`, `apply.py` now sits in `organize/cleanup/`).
  - **repo change needed**: delete the old `organize/cleanup.py` and
    `organize/preimport.py` files when dropping in the new
    `organize/cleanup/` and `organize/preimport/` directories — a
    stray flat file alongside the package directory would shadow it.
  - regression tests for both packages still need writing/updating
    against the new module paths (`tests/organize/test_cleanup.py`,
    `tests/organize/test_preimport.py`), and `PACKAGE_OVERVIEW.md`
    still needs its `organize/` section rewritten for the new layout
    (see above).

---

## Resolved (historical)

Compressed from an earlier session's full log — the detail (which files,
which tests, which exact lines) isn't load-bearing anymore now that
`PACKAGE_OVERVIEW.md` describes the current state directly; kept here
only so the "documented as done ≠ actually done" lesson stays visible.

- [X] Post-refactor smoke testing found and fixed three import-breaking
  gaps `PACKAGE_OVERVIEW.md` had described as already done:
  `download.existing.resolve_output_dir()` missing entirely,
  `download/manifest.py` missing as a file, and `retry.py` missing
  `import re`. Motivated `NEW_FEATURE_GUIDE.md`'s "actually run it"
  checklist.
- [X] Verified `download.manifest`'s album-column guess, the
  `existing.py` docstring, `spotify_export.py`'s blank-line-on-no-url
  behavior (pinned intentional), and the `conftest.py` fixtures against
  real usage/exports.
- [X] Fixed `playlists/build.py`'s default-scope bug — was filtering
  `playlists.csv`'s `owner` (display name) against `SPOTIFY_USER_ID`
  (user ID), so the default "just my playlists" scope never matched.
  Now uses a dedicated `owner_id` column. Playlists exported *before*
  this fix need re-exporting to pick up `owner_id`.
- [X] Built out `tests/` through `lib/`, `download/`, `organize/`,
  `playlists/`, `tapedeck/` (§0–§5 of `TEST_PLANS.md`). `core/` (§6) is
  the only package still pending.
- [X] Fixed a stray lowercase-`ffmpeg_path` env-var fallback in two test
  fixtures that bypassed `lib.paths.ffmpeg_path()`.

---

## Album-name normalization / edition collapsing

- [X] **Shared album-name normalization layer for matching + grouping —
  implemented and smoke-tested.** `lib/text.py` gained
  `strip_edition_suffix(s)`/`normalize_album(s)`: a conservative,
  delimiter-anchored suffix stripper (parens/brackets, or a trailing
  dash/colon clause only — never bare mid-title) covering `(Deluxe)`,
  `(Deluxe Edition)`, `(25th Anniversary Edition)`, `(Remastered)`,
  `(Remaster)`, year-based remasters (`(2009 Remaster)`/`(Remastered
  2009)`), and stacked suffixes (`(Deluxe) (2011 Remaster)`). A
  parenthetical that doesn't match the keyword pattern — `(Ohia)`,
  `(Original Soundtrack)` — is left untouched by design.
  - [X] Wired into `lib.catalog.matcher`'s tiers 3 and 6b (the only two
    tiers that compare album at all — tiers 1/2/4/5 are title+artist-only
    and untouched). A Spotify row's `Album` now matches a local file
    tagged `Album (Deluxe)`/`Album (2009 Remaster)`.
  - [X] Wired into `organize.cleanup.grouping.group_files()`'s grouping
    key, so a track tagged `Album` and one tagged `Album (Deluxe)` land in
    the same group instead of forking — **merge-on-ingest**, the option
    chosen over a separate opt-in cleanup pass for now.
  - [X] Wired into `organize.preimport.plan.index_existing_albums()`/
    `build_plan()`'s merge-target key, so a freshly-downloaded edition
    variant merges straight into the existing plain-album crate folder
    instead of staging a sibling folder for resplit to untangle later.
  - [X] Verified against real fixtures, not just diffed: tier 3/6b
    isolation tests (title+album match with disjoint artists, and a
    symbol-only title anchored by `(album, track)` position), plus a
    `group_files()`/`build_plan()` fixture confirming two edition-variant
    tracks land in one destination folder, and an
    `index_existing_albums()`/`build_plan()` fixture confirming an
    incoming `Title (Deluxe)` track merges into an existing `Title`
    crate folder with zero staged (sibling) folders.
  - [X] `PACKAGE_OVERVIEW.md` updated: `lib/text.py`,
    `lib.catalog.matcher`, `organize/cleanup/grouping.py`,
    `organize/preimport/plan.py` sections, plus the cross-cutting
    consolidated-primitives note.

- [ ] **Not done — resplit destination naming.**
  `resplit_plan.py`'s `_name_album_component()` still names/disambiguates
  purely by raw `canonical_albumartist()`/`dominant_album()` strings +
  `(2)`/`(3)` suffixing; it doesn't consult `normalize_album()` to detect
  that a resplit piece is actually an edition variant of an existing
  crate folder. Low priority now that merge-on-ingest should prevent most
  *new* edition forks from reaching resplit in the first place, but a
  pre-existing edition-variant fork already on disk would still resplit
  into a numbered sibling rather than merging. Same underlying issue as
  the pre-existing "resplit destination collision" item below — worth
  fixing both together if either comes up again.
- [ ] **Not done — explicit metadata/folder-cleanup path.** No command
  writes a canonical album string back to tags or renames an
  already-existing folder pair (e.g. an old `Album` and `Album
  (Deluxe)` folder that both predate this fix, sitting as two separate
  folders today). Merge-on-ingest only affects new imports going
  forward. If this is wanted, it's a new opt-in `organize cleanup` flag
  (dry-run by default, same convention as everything else) — deliberately
  deferred rather than bundled in, per `NEW_FEATURE_GUIDE.md`'s "decide
  what 'everything' means before building it."
- [ ] Regression tests still owed as real `tests/` cases (the fixtures
  used to verify the above were standalone scripts against a temp
  package tree, same "still needs wiring into the actual suite" gap as
  Bug 2's fix had before it was closed out): `tests/lib/test_text.py` for
  `strip_edition_suffix`/`normalize_album`, a matcher fixture test for
  tier 3/6b, and `tests/organize/test_cleanup.py`/`test_preimport.py`
  cases for the grouping-key changes.

## Enhancements

- [ ] SoundCloud export/download + a `--exclude` flag for Spotify
  playlist sync + the cross-service playlist design both feed into —
  full plan in `PLAYLIST_SYNC_PLAN.md` (new), superseding the shorter
  note this bullet used to be. Short version:
  - `download soundcloud` (new subcommand, mirroring `download export`/`download spotify`'s split) lands in `download/`, not a new
    top-level package, via `yt-dlp extract_flat` — same reasoning as
    before, still just leaning that way rather than deciding it forever.
  - `--exclude NAME_OR_ID` (repeatable) on `playlists/build.py`'s
    `_select_playlists()`, so specific playlists (soundtrack/personal
    ones you don't want synced) can be skipped from `--apply --rescrape`/`core sync` without needing `-p` to enumerate everything
    else by hand.
  - Longer-term: a `core`-level workflow that chains rescrape → match →
    autodownload-unmatched → rematch for either service, which is what
    the eventual web app's downloader/sync pages actually want
    underneath them. See `PLAYLIST_SYNC_PLAN.md` §3 for why this should
    wait until the exclude flag and the SoundCloud manifest both exist.
- [ ] `core/` (§6 of `TEST_PLANS.md`) is the only package without a real
  test suite yet — the other five are done.
- [ ] `tapedeck/copy.py`'s `unstage()` prunes empty directories with a
  single bottom-up `os.walk`, so a parent directory that only becomes
  empty *because* its own child was just removed in the same pass isn't
  re-checked, and survives until a later unload's prune pass. Pinned as
  current behavior in a test, not fixed — decide whether it's worth a
  follow-up (two pruning passes, or a fixed-point loop) or is fine as
  documented behavior.

## `app/`

Not started. See `WEB_APP_PLAN.md` for the constraints and shape already
agreed on (no subprocess/CLI dependency from below), plus its new
"Feature-set decision" and "Progress reporting" sections — the feature
list is now scoped down against what Navidrome's own web app already
covers, and progress-reporting has a concrete recommendation instead of
being fully open.
