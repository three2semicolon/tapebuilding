# tapebuilding — todo

The `pipelines/` → `core/` refactor (`lib/` foundation + per-package
`cli.py` split + in-process `core/`) is complete. See `PACKAGE_OVERVIEW.md`
for current state and `README.md` for usage.

**Current focus: get `organize cleanup` to converge on the live crate.**
A real dry run over 11,519 files proposed ~220 moves that are almost all
wrong or non-idempotent (singles pulled into albums, real compilations
dissolved into one artist, `(2)` swaps, case-only folder flips). Root causes,
fix order, and acceptance gates are in `BUGFIX_PLAN.md` — read that before
touching code. The end state is: apply once, and the next dry run proposes
zero moves and zero tag writes. **All decisions are now made** (D1–D9, see
bottom of that section); three new bugs (13–15) were found reading the
organize source.

---

## Organize / library cleanup (active — see `BUGFIX_PLAN.md`)

### Closed

- [X] **Bug 1 — multi-artist tracks in `unmatched.csv`.** Root cause was the
  catalog cache never invalidating, not artist splitting. `get_index()` now
  does a stat-only `_is_stale()` check; regression tests in
  `tests/lib/catalog/test_indexer.py`; `PACKAGE_OVERVIEW.md` updated.
- [X] `cleanup.py`/`preimport.py` split into `organize/cleanup/` and
  `organize/preimport/` subpackages; public names re-exported from each
  `__init__.py`. (Stray flat `cleanup.py`/`preimport.py` must not coexist with
  the package directories.)
- [X] Album-name normalization layer: `strip_edition_suffix()`/`normalize_album()`
  in `lib.text`, wired into matcher tiers 3 and 6b, `group_files()` and
  `index_existing_albums()`. (Its *use in organize grouping* is being replaced
  by `group_album_key()` below; matcher keeps `normalize_album()`.)
- [X] `resplit.py` missing `sanitize` import — fixed.
- [X] `organize cleanup --check-tags` exists (scan singles/albums for
  corrupted `albumartist`).

### Reopened / new — in fix order

**Phase 0 — safety net (before any `--apply`)**

- [X] Move/tag **journal** (`<crate>/.organize_journal.jsonl`) written before
  each action → undo + resumable runs.
- [X] Back up `beets.db` + `.playlist_index.jsonl`; confirm a recent
  `library.csv` export or filesystem snapshot.
- [X] **Bug 15:** `rebuild_db()` renames `beets.db` to a timestamped backup
  instead of `os.remove()`.
- [X] Journal must cover `preimport/apply._apply()` and `check_tags(apply=True)`
  too, not only `run_cleanup()`.
- [X] *(code done; run V8 to see existing damage)* **Bug 13 (any time, before the next `organize import`):** fix
  `normalize_artists.py` — `_FEAT_RE` has no word boundaries (`Daft Punk` →
  `Da feat. Punk`, `Soft Cell` → `So feat. Cell`); drop the `_COLLAB_X_RE`
  misfire; `_normalize_list` joins with `, ` (D8). Run V8 first to see
  existing damage.
- [X] Import smoke test: `python -c "import organize.cli, organize.preimport.apply, organize.cleanup.resplit"`; confirm
  `organize/cleanup/__init__.py` re-exports `check_tags` (it lives in
  `apply.py`).

**Phase 1 — `lib/` primitives**

- [x] `lib.text.group_key()` / `group_album_key()` — Unicode-aware (NFKC +
  casefold + keep `\w`), never `''` for non-blank input. **Do not change
  `normalize_key()`** — matcher tier 6 and download filename matching depend
  on its ASCII-only/`''` behavior. (Bug 4)
- [x] `lib.tags.write_tag()`: compare exact NFC strings, not `normalize_key`,
  so case-only/non-Latin fixes actually write and identical values no-op. (Bug 7)
- [x] `lib.tags`: deterministic tie-breaks in `dominant_album()` /
  `canonical_albumartist()`; `canonical_album()` (merge editions, keep the
  edition marker — D2); `same_path()` + case-aware `safe_move()` (two-step
  for case-only); shared `member_filename()` / `single_filename()` /
  `unique_name()`; sort `scan_audio()` output. (Bugs 3b, 6)
- [x] `lib.text.fold_key()` (NFKD fold, `''` for non-Latin = no evidence;
  matcher veto only) alongside `group_key()`.
- [x] `lib.tags.read_tags()` adds `disc` (D5); force one `--reindex` after.
  `lib.tags.find_duplicates()` (same `group_key` artist+title, ≤ ~2 s, never
  across differing `disc`) shared by cleanup + preimport.
- [x] **Bug 12:** `lib.catalog.indexer._SKIP_TOPLEVEL` += `duplicates`,
  `unorganized` (D7). `unorganized/` is handled by `preimport` + `import`,
  which move files into `albums/`/`singles/` before they're indexed. Must land
  before duplicate quarantine.
- [x] Tests: `tests/lib/test_text.py`, `tests/lib/test_tags.py`, indexer skip-list.

**Phase 2 — grouping logic**

- [ ] **Bug 2b:** shared `split_group()` (raw-`artist` union-find promoted from
  resplit, compilation guard, self-titled-single signal, ambiguity reported not
  guessed) used by `cleanup/grouping.py` and `preimport/plan.py`. Any group
  size, not just two.
- [ ] **Bug 2b/4 addendum:** `split_group()` tokenizes with `group_key()` and
  discards `''` — today two unrelated non-Latin artists both tokenize to `''`
  and count as "sharing an artist". Also convert the `check_tags` helpers
  (`_is_collaboration`, `_is_known_label`, the `aa == artist` compare).
- [ ] **Bug 4:** never merge on an empty key; use `group_album_key`.
- [ ] Singles are destinations too: same collision/duplicate handling as
  album folders (`GEOTHEORY - LEVITATE (2)` etc.).
- [ ] `build_plan()` returns a `Plan` dataclass instead of a 7-tuple;
  preimport's report-dict keys stay stable.
- [ ] **Bug 14:** preimport duplicate check uses `normalize_key(title)` → every
  non-Latin title is `''` → false duplicates quarantined. Replace with
  `find_duplicates()`.
- [ ] **Bug 5:** delete the "Various Artists → most common artist" override in
  `grouping.build_plan` (dissolves real compilations; why the summary says
  `'Various Artists' albums: 0`).
- [ ] **Bug 6:** incumbent-keeps-name collision handling; quarantine true
  duplicates to `duplicates/`; keep-existing-folder rule (case-insensitive
  exact match reuses the existing folder); planner asserts no duplicate/occupied
  destinations.
- [ ] **Bug 3b:** `index_existing_albums()` returns the raw album string;
  preimport merges compute `canonical_album()` over incoming ∪ existing.
- [X] **Bug 10 (fixed in Phase 0):** `run_cleanup()` `UnboundLocalError` (`moved` defined inside
  one `if`, used in the next).
- [ ] `preimport/plan.py`: remove dead `if … : pass` no-op.
- [ ] **`organize import` leftovers report:** beets runs `--quiet` and skips
  uncertain matches, leaving files in `unorganized/`; with the indexer no
  longer seeing that dir they'd reappear in `unmatched.csv` and get
  re-downloaded. Report the count (and paths in `--verbose`) in the return
  value of `run_import()` / `core download-songs`.
- [ ] Gate: known-answer fixtures (listed in `BUGFIX_PLAN.md`) + real dry run
  reviewed by hand.

**Phase 3 — artist-credit rendering + `sanitize()` (isolated, high churn)**

- [ ] Plugin fix + `, ` join (D8) shipped before this phase if not already.
- [ ] **Bug 9 / D1:** `render_credit()` — split on `/` only, join with `, `;
  `&` and `,` inside credits untouched. Used for filename artist part and
  album-folder albumartist part. `sanitize()` substitutes `_` (beets-style)
  instead of deleting, for titles/albums/everything else. Tags are **not**
  rewritten (D9).
- [ ] Dry run lists distinct `/`-containing credits with counts → build the
  `AC/DC`-style allowlist (renders `AC_DC`).
- [ ] Land alone: dry run → review rename list → apply → rebuild db →
  reindex → `core sync`.

**Phase 4 — retire resplit (D4)**

- [ ] Confirm the regular pass reproduces what resplit was for (fixtures in
  `BUGFIX_PLAN.md`), then delete `resplit.py` / `resplit_plan.py`, the
  `--resplit` option + its `--rebuild-db` / `--check-tags` conflict checks in
  `cli.py`, `run_resplit` in `organize/cleanup/__init__.py`, the README
  paragraph, docstring mentions in `grouping.py`/`apply.py`, and
  `PACKAGE_OVERVIEW.md`. **Don't run `--resplit` before then** (it
  renumbers by position and blanks `albumartist`/`album` on singles).

**Phase 5 — converge on the live crate**

- [ ] Snapshot `unmatched.csv` before the first `--apply`.
- [ ] dry run → `--apply --no-tag-write` → dry run empty of moves →
  `--apply` → dry run **completely empty** → `--check-tags` (also repairs the
  empty `albumartist` on singles old resplit created) → `--rebuild-db` →
  `core sync`.
- [ ] Diff `unmatched.csv` against the snapshot. Renames can't change matches
  (matcher reads tags only); tag rewrites can. Rows that were only "matched"
  via `duplicates/`/`unorganized/` will now show as unmatched — expected.

**Phase 6 — tests + docs**

- [ ] `tests/organize/test_cleanup.py`, `test_preimport.py` from the
  known-answer fixtures (no resplit tests — it's retired).
- [ ] **Idempotency test:** apply plan to a temp tree, re-plan, assert empty
  (NTFS ordering with `X (2)` first, case-only variants, three-way dupes,
  non-Latin and `?` albums, VA compilation, collision singles, slash-joined
  credits, `Album` + `Album (Deluxe)`).
- [ ] `PACKAGE_OVERVIEW.md` (`lib/text.py`, `lib/tags.py`, `lib/catalog/indexer.py`,
  `organize/*`, cross-cutting note on organize-vs-matcher keys), `README.md`
  for any flag changes incl. `--resplit` removal.

**Phase 7 — matcher precision (after the library is clean; D6 decided)**

- [ ] Measure first — V6 (extended: would-be-vetoed set, ≤ 1 s same-album
  subset, hard-gate collateral, accent-only matches) and V9 (non-Latin rows).
- [ ] **Bug 11 / D6:** `_artists_contradict()` (fold_key sets, both non-empty,
  fully disjoint; VA entries = no evidence) → veto in tier 3 and tier 5; tier 3
  also gets a hard duration gate when both durations are known; tier 4 gets
  the reverse-direction lookup (Spotify `Title (feat. X)` vs plain local
  `Title`). Tiers 1/2/4/6 stay soft on duration. NOT "skip tier 3 for
  self-titled" / "require overlap" — those regress accent and non-Latin matches.
- [ ] Only if V6 says so: relax the veto with a ≤ 1 s escape hatch
  (label-tagged VA compilations).
- [ ] If V9 > 0: a fully non-Latin title+artist+album track **can never
  match** (tier 6a anchor fails) → `unmatched.csv` forever, re-downloaded by
  autodownload. Unicode keys in the matcher then become required, and a hard
  prerequisite for `PLAYLIST_SYNC_PLAN.md` §3.

**Superseded / folded in**

- ~~Bug 3 album-tag unification~~ → **Bug 3b**, Phase 1–2: the old
  `normalize_key`-gated loop never fires on `4x4 SCORPION` vs `4 X 4 Scorpion` (keys are equal). Needs exact-string comparison + edition
  policy (**D2**).
- ~~Resplit destination collision / naming via `normalize_album()`~~ and the
  rest of the resplit defect list → resplit is being **retired** (D4, Phase 4).
- ~~Making metadata changes alongside folders~~ → Bug 3b.
- ~~Normalization of album titles with matching info (deluxe-style)~~ →
  `group_album_key()`.

### Decisions (details in `BUGFIX_PLAN.md`) — all decided

- **D1** artist credits render as `, ` in filenames and album folder names
  (slash → `, `; `&`/`,` inside a name left alone).
- **D2** editions merge; keep the edition marker in the album string.
- **D3** duplicates → quarantine to `duplicates/` (never delete).
- **D4** retire `--resplit`.
- **D5** add `disc` to `read_tags()`; ordering + duplicate guard only,
  filename template unchanged.
- **D6** matcher tiers 3/5: artist-contradiction veto (fold_key, evidence-only),
  tier-3 hard duration gate, tier-4 reverse lookup.
- **D7** indexer skips `duplicates/` and `unorganized/`.
- **D8** beets plugin joins with `, ` (new imports only; bundled with Bug 13).
- **D9** names only — `artist`/`albumartist` tags stay as stored (`/`).

### Quick checks to run first (cheap, settle open questions)

- [ ] `Yeat - 2093 (P2)`: read the real album tag (likely not a bug).
- [ ] Adhesive Wombat `02 → 03`: read the `track` tag (expect 3; confirms
  resplit's `idx+1` renumbering).
- [ ] XXXTENTACION `?` album: confirm `normalize_key()` → `''`.
- [ ] V6 (extended, see `BUGFIX_PLAN.md`): tier-3/5 matches with disjoint
  fold_key artist sets, the ≤ 1 s same-album subset, hard-gate collateral,
  accent-only matches.
- [ ] V8: artist tags mangled by the plugin (`feat.` after ≤ 3 chars).
- [ ] V9: rows/entries with empty title key *and* empty primary-artist key.
- [ ] V10: albums with repeated track numbers across discs (after `disc`
  is readable).
- [ ] `Ital Tek - Control\09 - Janet Jackson …`: confirm `albumartist` is
  `Ital Tek` (poisoned tag).

---

## Enhancements

- [ ] spotdl fallback, option to turn on so that each song/album that cant be found (spotdl) asks user to input either the youtube music or mu
  _(original note was cut off mid-sentence — finish this thought)_
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

---

## Feature-set decision (planning session update)

Navidrome's own web app already covers browse/search/play well — that's
not something `app/` needs to duplicate. Scoping `app/` to what Navidrome
*doesn't* do:

1. **Playlist management** — create/rename/delete, move tracks between
   playlists, reorder. Covers both Spotify-sourced local `.m3u8`s and
   (once built, see `PLAYLIST_SYNC_PLAN.md`) SoundCloud ones.
   - **Design question this raises:** does `app/` manage the local
     `.m3u8` files that feed Navidrome's own scan (so a change here needs
     Navidrome to notice — the same scan-trigger-vs-file-watcher
     question `TODO.md`'s Phase 1 already flagged), or does it read/write
     Navidrome's own playlist records directly via the Subsonic API?
     These are two different implementations with different sources of
     truth. **Recommend the former** — keep the `.m3u8` + crate + matcher
     model this repo already has as the one source of truth, and let
     Navidrome just scan the result, rather than introducing a second
     playlist store that can drift out of sync with it.
2. **Downloader page** — paste a Spotify/SoundCloud track/playlist/album
   URL, it runs the equivalent of `download spotify`/`download soundcloud`/`download ytdl` under the hood, shows live progress, drops
   the result into the crate. This is the strongest case for actually
   deciding the progress-reporting question now (see below) — a
   multi-minute download run has no synchronous-request-friendly shape.
3. **Command runway** — `core sync`, `organize cleanup` (and, once built,
   `organize cleanup --resplit` — see `BUGFIX_PLAN.md`), per-service
   playlist refresh, run from a jobs page. Recommend a plain "run this
   job, show me the log tail + final ok/fail" surface rather than a
   bespoke UI per command, at least for a first pass.

None of the above is something Navidrome's web UI + Subsonic API gives
you for free — it doesn't run arbitrary local Python or trigger
downloads — so building `app/` for this is still worth it.

## Progress reporting — recommendation

Previously left fully open (see "Not yet decided" above); the downloader
page above makes this concrete enough to actually propose something
rather than leave it open indefinitely.

- **Job store:** a small in-process module (e.g. `core/jobs.py` or
  `app/jobs.py` — either works, since `app/` can import `core/` directly
  per the constraints above) wrapping a background thread per job,
  storing `{'id', 'state': running|ok|error, 'log': [...], 'result': ...}` in memory (or a tiny sqlite/json file if `app/` needs jobs to
  survive its own process restarting).
- **Bridging the print()-narration problem:** most domain functions
  narrate progress via bare `print()` today. Two ways to surface that
  without rewriting every domain function:
  - **(a)** redirect stdout during the job's thread and append each line
    to the job's log — zero changes to domain code, but no structure
    (can't tell "%-done" from a plain log line).
  - **(b)** thread an optional `on_progress(event: dict)` callback
    through the handful of functions that already return structured
    per-step data (`run_download_songs()`'s `steps` list,
    `download_spotify()`'s per-batch loop, `run_retry()`'s counts), so
    the job store gets real structured events where they're cheap to
    add, falling back to (a) everywhere else.
  - **Recommend starting with (a) everywhere** (fastest, no domain-code
    changes), layering **(b)** in only for `download_spotify()`'s
    (and, once built, `download_soundcloud()`'s) per-track loop
    specifically — that's the one place "still running…" is a
    noticeably worse UX than "3/47 tracks."
- **Frontend:** poll `/jobs/<id>` on an interval. Simplest option, no
  websockets needed for a single-user LAN/Tailscale app. Revisit
  SSE/websockets only if polling feels laggy in practice — don't build
  that up front on spec.

## Symfonium mobile playlist management — investigated

Checked current state rather than going on the "doesn't seem I can
add/manage playlists from there" impression: Symfonium **can** create,
edit, and push/sync playlists to Navidrome — it's supported, not missing
— but two things likely explain why it looked broken:

1. **Import isn't automatic.** A playlist created in Navidrome doesn't
   just show up editable in Symfonium — each one needs an explicit
   one-time **Import** action before Symfonium will let you edit it and
   push changes back. Users hitting this exact confusion is a recurring
   thread on Symfonium's own support forum.
2. **Sync is one-directional per action, not a merge.** "Push to server"
   fully overwrites the server copy with your local one; "pull from
   server" does the reverse. Editing the same playlist from two
   devices/apps between syncs can silently clobber changes rather than
   merging them — worth knowing before leaning on it as your only edit
   path.

**Recommendation:** try the explicit per-playlist Import step before
falling back to `tapedeck` for playlists you expect to edit a lot — keep
`tapedeck` as the fallback specifically for playlists you don't want
round-tripping through that one-directional sync model at all, which is
what `TODO.md` already anticipated ("worst case I'll just use the
tapedeck to load certain playlists").

Source: [Symfonium support forum, &#34;Playlist
Support Question&#34;](https://support.symfonium.app/t/playlist-support-question/7626).
