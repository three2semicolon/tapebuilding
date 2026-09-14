# tapebuilding — new feature guide

What to check, in order, before considering a new feature (or a change
to an existing one) actually done — written so an AI (or a human working
fast) has a fixed checklist instead of relying on memory of the whole
repo. Pairs with `PACKAGE_OVERVIEW.md` (what exists) and
`TEST_PLANS.md` (what should be tested).

The single biggest lesson behind this doc: **this session found three
import-breaking bugs in code that `PACKAGE_OVERVIEW.md` confidently
described as already done** (`download.existing.resolve_output_dir()`,
the entire `download/manifest.py` module, and a missing `import re` in
`retry.py`). None of them were caught until someone ran the actual
command. Documentation describing intended state is not evidence the
code matches it — actually running the thing is the only check that
counts.

---

## 1. Figure out where it belongs

Decision order:

1. **Does it need to be shared by two or more domain packages, and does
   it not itself depend on any domain package?** → `lib/`. Check
   `PACKAGE_OVERVIEW.md`'s `lib/` section first — there's a real chance
   the primitive you need already exists there (path resolution, text
   normalization, tag reading, m3u8 read/write, Spotify auth, the crate
   catalog). Don't write a fifth copy of something `lib/` was created
   specifically to stop duplicating.
2. **Is it a single, focused capability inside one domain
   (`download`/`organize`/`playlists`/`tapedeck`)?** → goes in that
   package, as a plain importable function (not a `cli.py`-only thing —
   see §3).
3. **Does it orchestrate multiple domain packages into one opinionated
   workflow?** → `core/`, following the shape of
   `core.download_songs.run_download_songs()` /
   `core.sync.run_sync()` (call domain functions directly, return a
   structured result, no subprocess/CLI shelling).

**Dependency direction is a hard rule, not a preference:** `lib/` never
imports from a domain package. Domain packages may import from `lib/`.
`core/` may import from any domain package. The **only** currently
permitted domain-to-domain dependency is `playlists → download` (for
auth + export) — confirmed by a full-repo grep at refactor time. If your
new feature needs a second domain-to-domain import, that's a signal to
either move the shared logic into `lib/` instead, or to explicitly
update the "Cross-cutting notes" section of `PACKAGE_OVERVIEW.md` to
document the new edge and why it's not going through `lib/`. Don't add
the import silently.

---

## 2. Match the existing conventions before inventing new ones

- **No `sys.exit()` or `print('--help')` below `cli.py`.** Every domain
  function needs to be safely importable and callable from `app/`
  (unbuilt, but planned — see `WEB_APP_PLAN.md`) or from a test, not
  just from a terminal invocation.
- **Return structured data, don't rely on `print()` for anything a
  caller needs to make a decision on.** `print()` is fine for progress
  narration a human is watching; a dict/bool return is what `cli.py`
  (or a future `app/`, or a test) actually consumes. Look at
  `core.download_songs.run_download_songs()`'s `{'steps': [...], 'ok':
  bool}` shape or `download.retry.run_retry()`'s full breakdown dict for
  the pattern.
- **Dry-run means "run for real in no-op mode," not "skip."** This
  project deliberately moved away from the old subprocess pipeline's
  "print the command, run nothing" dry-run — a new dry-run-capable
  feature should do a real (but non-mutating) pass: an existence check
  instead of a download, `--pretend` instead of an import, a preview
  instead of a write. Skipping the step entirely in dry-run mode is
  the specific old behavior this project moved away from — don't
  reintroduce it.
- **`--apply`-gated by default, except where the command's whole point
  is writing** (e.g. `core sync` / `playlists --rescrape` has no
  dry-run mode of its own — preview via `build_playlists(apply=False,
  ...)` directly instead). If you're adding a command, decide explicitly
  which category it's in rather than defaulting to whichever is easier
  to write.

---

## 3. Environment variables

- **Uppercase only.** The old dual-case fallback
  (`ARCHIVE_PATH`/`archive_path`) was deliberately dropped
  project-wide. Don't add a new env var with a lowercase fallback, and
  don't resurrect one on an existing var (this exact regression — a
  stray `os.getenv('ffmpeg_path')` lowercase fallback — showed up in an
  old pre-refactor file this session and should stay dead).
- **Route every new root path through `lib.paths.resolve()`**, not a
  bare `os.getenv()` call — even if it feels like a one-off. That's the
  one place the `cli` > `env` > `default` precedence and the
  `required=True` error message live; a bare `os.getenv()` bypasses
  both.
- **Decide fallback vs. `required=True` based on one question: does
  this operation move, rename, or delete files on disk?** If yes,
  require the path explicitly with no guessed default
  (`organize.cleanup.resolve_crate()` and
  `organize.beets_import.run_import()` are the existing examples — both
  call `resolve('ARCHIVE_PATH', required=True)` directly rather than
  using `archive_path()`'s convenience default). If the operation is
  read-mostly (an existence check, a playlist rebuild that fails soft
  into `unmatched.csv`), a convenience default is fine.

---

## 4. Filename / matching correctness

If the feature touches predicting a filename spotdl or yt-dlp will
write, or matching an external record (Spotify row, CSV row) against a
file already on disk:

- **The prediction has to match the real tool's actual output exactly**
  — not "close enough." `download.manifest.sanitize_filename()` exists
  specifically because `--pre-skip-existing` compares a *predicted*
  filename against what's *actually on disk*; any drift between the
  prediction and spotdl's real sanitization silently breaks the
  existence check (over- or under-counting "already downloaded"), and
  nothing will raise an error when it does — it'll just quietly
  re-download things or quietly skip things it shouldn't. Test this
  against a real downloaded file's actual filename, not just the
  function's own logic.
- **Reuse `lib.catalog.matcher`'s tiered approach and
  `lib.text`'s normalization functions** rather than writing new
  fuzzy-matching logic. If a new tier or a new normalization rule
  genuinely seems necessary, it belongs in one of those two modules
  (with a test pinning where in the tier order it sits), not as a
  parallel one-off matcher somewhere else.
- **Don't "fix" the intentional divergences.** `lib.text.split_artists()`
  deliberately does not treat `" and "` as a separator, while
  `organize/normalize_artists.py`'s beets plugin deliberately does.
  `lib.tags.primary_token()` deliberately differs from
  `lib.text.primary_artist()`. Both are pinned by design, not oversight
  — check `PACKAGE_OVERVIEW.md`'s module descriptions before "fixing" an
  inconsistency that might be intentional.

---

## 5. Before calling it done

1. **Actually run the command**, not just `import`-check the module
   mentally. `uv run <package> <subcommand> --help` at minimum; a real
   invocation against fixture/sample data if at all practical. This
   session's entire debugging chain (three sequential `ImportError`s)
   only happened because the refactor's completion was judged by the
   docstrings and `PACKAGE_OVERVIEW.md` saying a function existed,
   without anyone actually running the code path that imported it.
2. **Add at minimum an import smoke test** for any new/changed module —
   see `TEST_PLANS.md` §0. This is the cheapest test in the repo and
   would have caught every bug found this session.
3. **Add real unit/integration tests** per the relevant section of
   `TEST_PLANS.md`, or add a new section there if the feature doesn't
   fit an existing one.
4. **Update `PACKAGE_OVERVIEW.md`**: the module's description under its
   package section, and the "Cross-cutting notes" section if the
   dependency graph or the env-var list changed.
5. **Update `README.md`** if it's a user-facing CLI command or flag —
   the README is usage documentation, `PACKAGE_OVERVIEW.md` is
   implementation documentation; a new flag needs both.
6. **Update `TODO.md`**: remove the item if it's now done, or add a
   follow-up if the feature surfaced a new open question (the way
   `WEB_APP_PLAN.md`'s progress-reporting question was flagged rather
   than guessed at).

---

## 6. Known landmines (check against these specifically)

- `playlists/build.py`'s `_select_playlists()` default-scope filter
  compares `playlists.csv`'s `owner` column (a **display name**) against
  `SPOTIFY_USER_ID` (a **user ID**) — this almost certainly never
  matches, silently falling back to "build everything." Don't build a
  new feature on top of assuming default-scope playlist selection
  works correctly until this is fixed and tested (see `TEST_PLANS.md`
  §4).
- `download/manifest.py`'s `album` field is a **best-effort guess**
  (`album_name` or `album` column) that has not been verified against a
  real export CSV header. If a new feature depends on that field being
  populated, verify the real column name first.
- Anything documented in `PACKAGE_OVERVIEW.md` as already implemented
  should still be spot-checked by running it once, given this session's
  track record — treat the doc as a map, not a guarantee.
