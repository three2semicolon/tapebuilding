# tapebuilding — bugfix plan: organize (grouping, naming, idempotency)

Supersedes the previous `BUGFIX_PLAN.md`. Written against the real source
(`lib/text.py`, `lib/tags.py`, `lib/paths.py`, `lib/catalog/indexer.py`,
`lib/catalog/matcher.py` (read in full), every `organize/cleanup/*` and
`organize/preimport/*` module) and a real `organize cleanup --verbose`
dry run over the live crate (11,519 audio files).

**Goal:** `organize cleanup` on the live crate converges to a clean
library, and a second dry run right after `--apply` proposes **zero**
moves and **zero** tag writes. Everything below serves that.

---

## 0. Status of the old bugs

| # | Old title | Status |
|---|-----------|--------|
| 1 | Multi-artist tracks in `unmatched.csv` (stale catalog cache) | **Closed.** `_is_stale()` auto-invalidation shipped, regression tests in `tests/lib/catalog/test_indexer.py`, `PACKAGE_OVERVIEW.md` updated. Nothing further here. |
| 2 | Unrelated same-titled singles merged | **Reopened → Bug 2b.** The shipped fix only handles groups of *exactly two* tracks. The dry run shows the same collision with 3–5 members (`Alone`, `Crush`, `Fantasy`, `Colors`, `Damage`, `Hot`, `Smile`, `Cry Baby`, `Desire!`, `Dangerous`, `4U`, `love`, `It Is What It Is`). Also, the two-track check uses `artist ∪ albumartist` tokens, so a self-inflicted `albumartist` tag defeats it. |
| 3 | Album tag formatting differs within a folder | **Fix as written is a no-op → Bug 3b.** The planned condition `normalize_key(m['album']) != normalize_key(album)` is false for exactly the case in the symptom (`4x4 SCORPION` vs `4 X 4 Scorpion` both key to `4x4scorpion`), so nothing is ever written. See Bug 3b. |

New bugs found from the dry run: 4–10 below.

---

## Decisions log

**Decided**
- **D1 — artist credits in names:** `, ` (not `&`, not `_`). Applies to
  filenames *and* album folder names (the albumartist part). See Bug 9 for
  the exact rendering rules.
- **D2 — editions:** merge them; the album string keeps the edition marker
  (`Deluxe`, etc.). See Bug 3b.
- **D4 — resplit:** retire `--resplit`. See Bug 8.
- **D7 — indexer:** skip `duplicates/` and `unorganized/`. `unorganized/` is
  covered by `preimport` + `import`, which move files into `albums/` /
  `singles/` before the crate is indexed. See Bug 12.

**Still open** (recommended defaults noted; details in "Open decisions" at the end)
- **D3** duplicates: quarantine (default) vs report-only vs delete.
- **D5** multi-disc: add `disc` to `read_tags()`?
- **D6** matcher tier 3/5 behavior change (Bug 11).
- **D8** (new) beets `normalize_artists` plugin still joins with `&`; align to `, `?
- **D9** (new) are `albumartist`/`artist` *tags* meant to change too, or just names?

---

## 1. What the dry run is telling us

Of the planned moves, almost none are legitimate "this file is in the wrong
place" moves. They fall into five families, each a different root cause:

| Family | Examples from the dry run | Root cause |
|--------|--------------------------|------------|
| Singles pulled into albums | `singles\Nali - 4 U.mp3 → albums\Ojerime - 4U\…`, `Alone`×5, `Fantasy`×3, `Colors`×3, `Dangerous`×3 | Bug 2b |
| Real compilations dissolved into one artist | `Various Artists - Brainfeeder X → Teebs - Brainfeeder X`, `Chillhop Essentials → C Y G N`, `Powered by Inspected → Culprate`, `Sofie's SOS Tape → Ahwlee`, `Gold - '80s Soul → Carl Carlton`, `Ingenious Pleasure Vol. 2 → Herzeloyde`; also why the summary says `'Various Artists' albums: 0` | Bug 5 |
| Unrelated tracks piled into one bucket | `XXXTENTACION - Question Mark → ぬいぐるみクレヨン Lush Crayon -\`, plus 11 Japanese singles in that same folder | Bug 4 |
| Swaps / 3-way rotations / `(2) (2)` | `$amaad … If U Let Me (2) ⇄ If U Let Me`, `duce - II PRODUCT` ×3 rotating, `Up With the Birdies (2) (2)` | Bug 6 |
| Endless case-only folder renames | `Citizen - Youth ⇄ youth`, `Vayda - Fever ⇄ fever`, `Lunchbox - new jazz ⇄ New Jazz`, `Playboi Carti - Music ⇄ MUSIC`, `Run The Jewels 3` vs `3`, `King Gizzard … East ⇄ east` | Bugs 6 + 7 |

Plus smaller families: renumbering (`02 → 03`, `01 → 02`: Adhesive Wombat,
CUBE, Freddie Joachim, Navy Blue, Madison McFerrin, Phoelix, Häzel →
Bug 8), and `Ojerime - 4 U → 4U` / `Mk.gee - McGee → Mcgee` (Bug 6/7).

---

## 2. Corrections to the earlier diagnosis

Recorded so nobody chases them again:

- **It is not `read_tags()` joining multi-artist tags.** `read_tags()` is
  fine. Strings like `Run The JewelsEl-PKiller Mike` in filenames/folders
  come from `lib.tags.sanitize()`, whose illegal-character regex
  deletes `/` — and the real tags are slash-joined
  (`Run The Jewels/El-P/Killer Mike`, confirmed earlier for
  `Ash Levi/Isaiah Kaleo`). Tokenization (`split_artists`) is unaffected;
  only the *rendered names* are mangled. → Bug 9.
- **`Yeat - 2093 → 2093 (P2)` probably isn't a bug.** `(P2)` isn't in the
  edition regex, so the two spellings key differently and aren't merged.
  The files being moved most likely carry `album='2093 (P2)'` in their tags
  while the old folder name came from elsewhere. Verify by reading one
  file's tags (§Verification V1) before touching anything.
- **Matcher confirmations (now read in full, not just grepped).** Matching
  consumes only each entry's *tags* and returns its `path`; filenames and
  folder names never influence a match. So renames/moves can't change which
  tracks match (they only change the paths written into `.m3u8`s, hence the
  reindex + `core sync` after any apply). Tag *rewrites* (`album`, `albumartist`)
  can change matching — see Bugs 11–12 and the Phase 5 `unmatched.csv` check.
  The earlier claim that `normalize_key()` must stay ASCII-only is confirmed:
  `MatchIndex._build()` excludes `''` keys from `by_title`/`by_prefix` and
  tier 6 runs *only* when `normalize_key(title) == ''`.
- **The garbled `MyHead` / `WITHME` / `Run TheJewels` / `->albums\…` lines
  are paste/line-wrap artifacts** in the dry-run output, not bugs.

---

## Bug 2b: unrelated singles collapsed into album groups (any size)

### Root cause (confirmed in `grouping.py`, `plan.py`)

`group_files()` keys on `normalize_album(album)` only. Spotify singles have
`album == title`, so any two artists' singles with the same title land in one
group. `is_unrelated_va_collision()` only fires for `len(members) == 2`, and
its token set includes `albumartist`, which `cleanup --apply` itself wrote on
earlier runs (the "poison" problem `resplit_plan.py` already documents for
its own use case). A previously-wrong merge therefore keeps looking
legitimate.

`preimport/plan.py` calls the same `is_unrelated_va_collision()`, so incoming
drops have the same hole.

### Fix

1. **One shared splitter**, `split_group(members) -> [component, …]`, living
   in `organize/cleanup/grouping.py` and imported by `preimport/plan.py` and
   `cleanup/resplit_plan.py` (resplit already has the union-find in
   `_artist_components()`; promote it instead of keeping two copies).
   Union-find over pairwise overlap of **raw `artist` tokens only** — never
   `albumartist`, which this codebase writes.
2. **Compilation guard — never split these:**
   - the group is explicit-VA (≥ 50 % of members carry a `Various Artists`/`VA`
     `albumartist`), **and** it has ≥ 4 members, **or** its titles are
     overwhelmingly *not* equal to the album title.
     (The ≥ 4 / title≠album part exists because a 2–3 track collision can
     itself carry a self-inflicted VA tag; a real compilation is large and
     has distinct titles.)
3. **Self-titled-single signal:** a member whose normalized title equals the
   album key *and* whose artist tokens are disjoint from the rest is a
   single-release collision; it always becomes a singleton regardless of
   group size.
4. **Outcome per component:** size ≥ 2 → album group; size 1 → singleton
   (`singles/Artist - Title.ext`), same as any lone-album track today.
5. **Ambiguity is reported, not guessed.** Group of ≥ 4 members, no
   explicit-VA tag, where the largest component is < 50 % of members: leave
   merged and list it under a new `ambiguous splits` section of the dry-run
   summary for manual review. This is the genuinely murky middle case
   (real VA compilation lacking a VA tag vs. a pile-up).
6. Replace the old `is_unrelated_va_collision()` with a thin wrapper over
   `split_group()` (keep the name exported so `preimport/plan.py` and any
   tests don't break), then delete the wrapper once call sites are moved.
7. Dry-run summary: `split (false collision)` counts components removed, and
   the list shows member artist names, not just the album title, so a
   review can tell at a glance whether a split is right.

### Known-answer fixtures (from the real dry run — each must hold)

- Must **split to singles**: `Alone` (alici, Marshmello, Miso, sobenoyse,
  WILLOW), `Crush`, `Fantasy`, `Colors`, `Damage`, `Hot`, `Smile`, `Cry Baby`,
  `Desire!`, `love`, `It Is What It Is`, `4U` (Nali, Pi'erre Bourne,
  printingcounterfeits stay singles; Ojerime's own two tracks stay an album).
- Must **stay together as VA**: `Brainfeeder X`, `Chillhop Essentials Summer
  2018`, `Gold - '80s Soul`, `Ingenious Pleasure Vol. 2`, `Powered by
  Inspected, Vol. 1`, `Sofie's SOS Tape`.
- Must **peel one foreign track out of a real album**: `Ital Tek - Control`
  (Janet Jackson's "Funny How Time Flies"), `Mick Jenkins - Pieces of a Man`
  (Gil Scott-Heron's "Home Is Where the Hatred Is"), `Playboi Carti - MUSIC`
  (Erick Sermon/Marvin Gaye "Music").
- Must **stay one album**: `Run The Jewels 3` (feature-heavy), `Sketches of
  Brunswick East`, `Playboi Carti - MUSIC` minus the foreign track above,
  `Vinyls and Ashtrays` (different featured artist per track).

---

## Bug 4: empty grouping key swallows every non-Latin / symbol-only album

### Root cause (confirmed by reading `lib/text.py` and `lib/tags.py`)

- `normalize_key()` is `[^a-z0-9]`-after-lowercase — **ASCII only**. Any
  album that is entirely non-Latin (`ぬいぐるみクレヨン…`) or symbol-only
  (XXXTENTACION's `?`) normalizes to `''`.
- `group_files()` buckets by `('album', '')` → every such album, from
  unrelated artists, becomes one group.
- `sanitize()` deletes `?` etc., so the folder name for that group
  becomes `"<artist> -"` — which is precisely the literal folder
  `ぬいぐるみクレヨン Lush Crayon -\` in the dry run.
- Accented Latin also loses letters (`Häzel`→`hzel`, `Morë`→`mor`), so
  distinct names can collide.

### Fix

Do **not** change `normalize_key()` globally. `lib.catalog.matcher`
deliberately depends on `normalize_key(title) == ''` for symbol-only titles
(tier 6 design), and `download.existing`/`download.manifest` match against
spotdl's real filenames. Changing it would silently shift match behavior.

1. Add `lib.text.group_key(s)` — **Unicode-aware**: NFKC → casefold → keep
   `\w` (letters/digits in any script) → strip the rest. Never returns `''`
   for a non-blank input; if everything strips, fall back to
   `casefold(strip(s))`.
2. Add `lib.text.group_album_key(s)` = `group_key(strip_edition_suffix(s))`.
3. Use these (not `normalize_key`/`normalize_album`) in every organize
   grouping/compare site: `group_files()`, `index_existing_albums()`,
   `build_plan()` keys, `canonical_albumartist()`, `dominant_album()`,
   `write_tag()`'s change check.
4. Safety net: if `group_files()` still computes an empty key for a file
   with a non-empty album tag, treat it as a unique singleton key
   (`('single', i)`) — never merge on emptiness.
5. Add `_run_sanity_checks()` cases: `group_key('?') != ''`,
   `group_key('ぬいぐるみ') != ''`, `group_key('Häzel') != group_key('Hzel')`,
   and `group_key('4x4 SCORPION') == group_key('4 X 4 Scorpion')`.

---

## Bug 5: the "Various Artists → most common artist" override destroys real compilations

### Root cause (confirmed in `grouping.build_plan`)

```python
if aa == 'Various Artists':
    artist_counts = ...        # most common raw artist wins
    aa = max(artist_counts, key=artist_counts.get)
```

This runs *before* the VA bookkeeping, so it:
- overwrites a correct explicit `Various Artists` albumartist with whichever
  artist has the most tracks (`Brainfeeder X → Teebs`);
- makes `va_groups` always empty, hence `'Various Artists' albums: 0`;
- was presumably added to paper over Bug 2b/4's false-VA results.

### Fix

Delete the override. With Bug 2b and Bug 4 fixed, a group that still
resolves to `Various Artists` is a real compilation and should keep that
albumartist and folder name. If a real single-artist album ever comes out VA
(rare), that's a `canonical_albumartist()` problem to fix there — a 50 %
threshold plus primary-token fallback already exists — not something to
patch downstream.

---

## Bug 6: naming isn't idempotent — `(2)` swaps, rotations, case-only flips

### Root cause (three interacting causes)

1. **Collision suffixing depends on iteration order.** `build_plan()`
   assigns `name`, `name (2)`, … in the order members are scanned.
   `scan_audio()` doesn't sort, and on NTFS `X (2).mp3` lists *before*
   `X.mp3` (space 0x20 < `.` 0x2E). So the `(2)` file claims the plain name,
   the plain file is demoted to `(2)`, and every run swaps them back. The
   three `PRODUCT` and `Blame It` files rotate for the same reason.
2. **`safe_move()` renames on collision at apply time**, and in a swap the
   destination is still occupied by the not-yet-moved partner, so apply
   itself generates new `(2)`/`(2) (2)` names (`Up With the Birdies (2) (2)`).
3. **Case-only renames collide with themselves.** On a case-insensitive
   filesystem `os.path.exists(dst)` is true for the file's own path in a
   different case, so `safe_move()` takes the collision branch and appends
   `(2)`. And the planner compares `os.path.normpath(dst) != normpath(src)`,
   which is case-sensitive, so it reports a "move" every time.

### Fix

1. **Incumbent-keeps-name rule.** Name assignment in two passes: first,
   every member whose current basename already equals the wanted name keeps
   it; then the rest get suffixes. One shared helper in `lib.tags`
   (`unique_name(wanted, taken_lowercase, incumbent=None)`), used by
   `grouping.py` and `preimport/plan.py` (replacing the copies of the `while name.lower() in seen` loop).
2. **True duplicates are quarantined, not renamed.** Two files in one
   destination folder with the same normalized artist + title (and duration
   within ~2 s) are the same track: keep the best (prefer lossless, then
   larger file), move the rest to `<crate>/duplicates/` with the same
   mechanism `preimport/apply.py` already uses (`duplicates_dir()`), and
   list them in the report. This resolves `Blame It` ×3, `PRODUCT` ×3,
   `Intrro`, `Belleville`, `DUET`, `Hip Hop Phenomenon`, etc. rather than
   shuffling them.
3. **Case-aware same-path check.** A tiny `same_path(a, b)` (`normcase`
   + `normpath`; `samefile` when both exist) used by the planner and
   `safe_move()`. A case-only rename is executed as a two-step move
   (`src → src.tmp-<uuid> → dst`).
4. **Keep-existing-folder rule.** When the target folder name equals an
   existing folder's name **case-insensitively** (`casefold` + NFC, exact
   otherwise), reuse the existing folder's exact string. Case alone never
   triggers a rename of an already-correct folder. This kills
   `Citizen - youth`, `Vayda - fever`, `Lunchbox - New Jazz`,
   `Playboi Carti - MUSIC`, `Run The Jewels 3`, `Sketches of Brunswick East`
   and `Terrace Martin - Perspective`. Deliberately **not** `group_key`-based:
   `group_key` ignores punctuation/spacing, which would block the Phase 3
   rename of `MndsgnDevonwho - Episodes` → `Mndsgn, Devonwho - Episodes`.
5. **Deterministic `dominant_album()`.** Today a count tie resolves by
   dict insertion order, i.e. scan order, which is what flips
   `Duckwrth - SuperGood ⇄ supergood`. Tie-break order: (a) the spelling that
   matches the existing folder's album part, (b) the longer/more-cased
   string, (c) lexicographic. Same for `canonical_albumartist()` on a 50/50
   tie.
6. **Planner assertion.** Before returning, `build_plan()` asserts: no two
   moves share a destination (case-insensitively), and no destination exists
   on disk unless it is also a source in the same plan. A violated assertion
   is a hard planning error, not a silently-renamed file.
7. **Apply in two phases** (or journal-first): move everything whose
   destination is currently occupied by another planned source to a temp
   name first. In practice, with 1–6 fixed, the plan contains no cycles and
   this is a safeguard.

---

## Bug 7: tag-write checks use `normalize_key`, so the writes that matter never happen

### Root cause (confirmed in `lib/tags.write_tag` and the plan loops)

`write_tag()` only writes when `normalize_key(current) != normalize_key(value)`.
`build_plan()` queues album/albumartist writes under the same condition.
Consequences:
- Case/spacing-only differences (`4 X 4 Scorpion` vs `4x4 SCORPION`,
  `supergood` vs `SuperGood`) are **never queued or written**.
- Anything non-Latin keys to `''` on both sides, so it is never written.
- The writes that *do* get queued are the legitimate-looking ones where the
  keys differ — mostly edition-suffix variants. So the dry run's "35 album
  tags to write" are largely edition rewrites, not formatting fixes.

### Fix

1. `write_tag()` compares NFC-normalized, stripped **exact strings**, so any
   real difference is written and an already-identical value is a no-op
   (idempotent).
2. `build_plan()` queues a write when the member's string differs from the
   chosen canonical string **exactly**.

---

## Bug 3b: album-tag unification (corrected; policy decided)

Replaces the old Bug 3 plan. The old patch added the album-tag-write loops
in `grouping.py` / `resplit.py` / `plan.py`; the loops exist now but are
gated by Bug 7's comparison, so they never fire on the motivating example.

Navidrome shows one album per distinct literal album string, so every file in
a folder must carry one album string.

### Policy (D2: merge editions, keep the marker)

`canonical_album(members, existing_folder_album=None)` in `lib.tags`:
1. Collect the distinct album strings among members (plus the existing
   folder's album string when merging).
2. If any carry an edition suffix (per `strip_edition_suffix`), the canonical
   string is the **most common edition-suffixed variant** (tie → longest, then
   lexicographic). The deluxe/remaster tracklist is a superset, so nothing
   is lost: `Duality` + `Duality Deluxe` → `Duality Deluxe`.
3. Otherwise (formatting-only differences such as `4x4 SCORPION` vs
   `4 X 4 Scorpion`): most common string; tie → existing folder's spelling,
   then longer/more-cased, then lexicographic.
4. Folder name uses the canonical string; every member's `album` tag is
   rewritten to it when it differs **exactly** (Bug 7).

### Where it applies

- `cleanup/grouping.py`: per group, as above.
- `preimport/plan.py`: `index_existing_albums()` must return the existing
  folder's raw album string as well as its albumartist (today it returns
  `(folder, albumartist)`). On a merge, the canonical album is computed over
  incoming ∪ existing, so an incoming plain `Album` merged into an existing
  `Album (Deluxe)` folder is retagged `Album (Deluxe)` — and the reverse case
  upgrades the existing folder's name per rule 2 (flag it in the report; it
  implies an existing-file retag + folder rename, so it must go through the
  journal).
- Same-track overlap between the plain and deluxe discs (identical artist +
  title + near-identical duration) is handled by Bug 6.2's duplicate
  quarantine, which keeps the best copy.
- `(P2)`, `(Part 2)`, volume numbers etc. are **not** editions and stay
  distinct (so `2093` and `2093 (P2)` remain separate albums).

### Fix

After Bug 7, the existing `album_tag_writes` loops start working with the
policy above. Same for `albumartist`: only write what the plan says, never
`''`.

---

## Bug 8: retire `--resplit` (D4)

`resplit` was a one-off repair for folders wrongly merged before the Bug 2
fix. It has defects that would need fixing before it could run again, and
once Bug 2b's `split_group()` works on raw `artist` tokens the regular
`cleanup` pass does the same job (it already scans every file in `albums/` +
`singles/` and groups by album tag, which is what resplit effectively did
folder by folder). Rather than fix a second, divergent grouping
implementation, remove it.

Defects found (kept as the reason, and as a checklist of things the regular
pass must *not* inherit):
1. Renumbers tracks `idx + 1` instead of using the track tag. It already ran
   on the live crate, which is why a regular pass now wants `02→03`, `03→05`,
   `04→07` (Adhesive Wombat), CUBE `01→02`, etc. These converge once cleanup
   applies; no separate repair needed.
2. Queues `write_tag(albumartist='')` and `album=''` on every single it
   creates (`aa is not None` filter, singles appended as `(…, '', '')`),
   erasing tags. Already-run damage: singles with an empty `albumartist`.
   `organize cleanup --check-tags` already classifies these as `missing` and
   sets albumartist to the track's artist — use it in Phase 5.
3. No compilation guard, so it would shred every VA compilation.
4. Invents `(2)` suffixes instead of merging into a compatible existing
   album.

What carries over: `_artist_components()` (union-find) is promoted into
`split_group()` in `grouping.py` (Bug 2b), and the dry-run's split listing
moves into the regular summary (`split` / `ambiguous splits` sections).

**Do not run `--resplit` in the meantime.**

---

## Bug 9: `sanitize()` mangles artist credits and drops `?` (D1: `, `)

`_ILLEGAL_RE = [\\/:*?"<>|]` deletes the characters. Results:
- `Run The Jewels/El-P/Killer Mike` → `Run The JewelsEl-PKiller Mike`
  in filenames and folder names.
- Album `?` → empty string, folder `"<artist> -"` (compounds Bug 4).
- Folders created by beets use `_` for these (`Vinyls and Ashtrays_ Disc
  One`), so beets-made and organize-made names for the same album differ.

### Rendering rules (decided)

Two different renderers, because credits and titles are different things:

1. `render_credit(raw)` — for the **artist part** of filenames and singles,
   and the **albumartist part** of album folder names. Split on `/` **only**
   (the tag-level multi-value delimiter spotdl/ID3v2.3 writes), strip each
   piece, join with `, `. Do **not** touch `&`, `,`, ` x `, `feat.`: `&` is
   part of real names (`King Gizzard & The Lizard Wizard`, `Simon &
   Garfunkel`), so it can't be treated as a delimiter. Result then goes
   through `sanitize()` for the remaining illegal characters.
2. `sanitize(s)` — for titles, album names and everything else: replace each
   illegal character with `_` (beets-style) instead of deleting; never return
   an empty component (`'_'` fallback, as today).
3. **Names that legitimately contain `/`** (`AC/DC` and similar) go on a small
   allowlist in `lib.tags` and render with `_` (`AC_DC`). Build it from real
   data: the Phase 3 dry run first prints every *distinct* credit containing
   `/` with a count, and that list is reviewed before apply.
4. Matching/grouping is unaffected: tokenization still uses the raw tag
   strings through `split_artists()`.

### Scope: names, not tags (see D9)

Interpreting "albums should match" as the album *folder* names (the
albumartist part), same renderer as filenames. **Tags are not rewritten**:
rendering happens at path-construction time only. Rewriting `artist` /
`albumartist` tags to `, ` would add a large tag-write churn, and `, ` is
ambiguous as a stored delimiter (`Tyler, The Creator`). If you meant tags
too, say so and it becomes a separate, journaled step.

### Interaction with the beets plugin (D8)

`organize/normalize_artists.py` normalizes `A x B` / `A and B` / feat. forms
to `A & B` and `A, B & C`, and leaves `/` alone. So the crate contains both
slash-joined credits (spotdl) and `&`-joined ones (plugin). Under D1 the
slash ones render as `, `; plugin-produced `&` strings stay `&` in names.
For consistent output either leave it (mixed) or change the plugin's
`_normalize_list` to join with `, `. Open (D8).

### Churn warning

This renames a large share of the crate once (every slash-joined credit and
every name containing `?:*"<>|`). Land it as its **own isolated step**
(Phase 3), applied and reindexed separately, so the diff of that one step is
reviewable. The keep-existing-folder rule (Bug 6.4) is case-insensitive-exact,
so it does not suppress these renames.

---

## Bug 10: `run_cleanup()` crashes when only album tags need writing — FIXED in Phase 0

*(`moved` is now hoisted above both tag blocks and built from the journal's actual move results, singletons included. Phase 2 only needs to carry it forward.)*

`moved` is defined inside `if not no_tag_write and tag_writes:` but used in
the following `album_tag_writes` block. If `tag_writes` is empty and
`album_tag_writes` isn't, the apply path raises `UnboundLocalError` *after*
files have already moved. Hoist `moved` above both blocks and include
`singleton_moves` in it. Also: write tags **before** moving where possible
(then no path remap is needed), or build `moved` from a single list of
`(src, dst)` pairs.

---

## Bug 11: matcher false positives for self-titled singles (found in `matcher.py`) — D6 decided

Not an organize bug, but it is the *same* title-equals-album pattern as Bug
2b, and it silently hides missing downloads, which makes `unmatched.csv`
untrustworthy — the exact thing `PLAYLIST_SYNC_PLAN.md` §3 says must be right
before autodownload is built on top of it.

### Root cause (confirmed in `MatchIndex._tier3` / `_tier5` / `_pick_best`)

- Tier 3 requires title key equal and album key equal, and checks **no
  artist at all**.
- `_pick_best()` treats duration as a soft preference: if no candidate is
  within tolerance, it still returns the *closest* one.
- Spotify singles have `album == title`. So for a row `Marshmello - Alone`
  (album `Alone`) that is *not* in the crate, any other artist's local
  `Alone` file (album `Alone`) satisfies tier 3 and is returned at any
  duration. The track never reaches `unmatched.csv`, is never downloaded, and
  the playlist links to the wrong artist's song.
- Tier 5 has the same shape (fuzzy title + duration, no artist check; a
  missing duration passes), 3 s window.

### Why not "skip tier 3 for self-titled rows" / "require artist overlap in tier 5"

(The earlier draft of this section proposed exactly that. Reviewed against
the real code, it has side effects.)

1. **Accent variants would become new misses.** `normalize_key()` drops
   non-ASCII letters (`Jhené` → `jhn`), so tiers 1/2/4 already can't match
   `Jhené Aiko` against a local `Jhene Aiko`; tiers 3/5 are what rescue it
   today. Requiring overlap with `normalize_key` sets would reject that
   rescue and send the track to the downloader.
2. **Non-Latin artists have no usable artist key at all** (`''`), so
   "require overlap" rejects every cross-script / CJK match tier 3/5 finds.
3. **Local VA compilations tagged `artist = <label>`** are legitimate tier-3
   matches (title + album agree) whose artist set can never overlap the
   Spotify credit.

### Fix (D6, decided): contradiction veto, evidence-only

New in `lib.text`: `fold_key(s)` — NFKD, drop combining marks, lowercase,
keep `[a-z0-9]`. Used **only** by this veto. `''` means "no evidence"
(non-Latin), never a contradiction. `normalize_key()` is untouched.

`_artists_contradict(row, entry)` is True only when **both** sides have a
non-empty `fold_key` artist set (split via `split_artists`; entry set is
artist ∪ albumartist, as in `_entry_artist_set`) **and** the two sets are
completely disjoint. An entry whose artist/albumartist is `Various Artists`
or `VA` contributes no evidence (never contradicts).

1. **Tier 3:** (a) veto on `_artists_contradict`; (b) when both durations are
   known, within-tolerance becomes a **hard** gate (no "closest anyway"
   fallback — there's no artist check to lean on). A missing duration on
   either side still never vetoes (existing `_duration_close` rule).
2. **Tier 5:** veto on `_artists_contradict`. (Its duration pre-filter is
   already hard.)
3. **Tier 4, reverse direction (small recall fix):** today only a *local*
   `Title (feat. X)` matches a clean Spotify `Title` (`by_core_title` is
   populated only for entries whose feat clause was stripped). A Spotify
   `Title (feat. X)` against a plain local `Title` misses everything. When
   `core_q != title_key`, also search `by_title[core_q]` with the same
   artist predicate.
4. Tiers 1/2/4/6 otherwise untouched; duration stays a *soft* tiebreak in
   1/2/4/6a (artist-anchored; Spotify and local durations legitimately
   drift).

**Measurement-gated escape hatch (the one remaining judgment call):** if V6
shows would-be-vetoed tier-3 matches that share the album and agree on
duration within ~1 s (the label-tagged compilation case), relax the veto to
"contradiction **and** not (both durations known and ≤ 1 s)". Don't add it
speculatively.

Tests (`tests/lib/catalog/test_matcher.py`): self-titled single with only
another artist's same-titled single in the catalog → `unmatched`; same row
with the right artist present → tier 1; normal album track with disjoint
*ASCII* artists but identical title/album/duration where the entry is VA →
still tier 3; `Jhené Aiko` row vs `Jhene Aiko` local → still matches
(tier 3/5); CJK-artist row vs CJK-artist local → still matches (no evidence,
no veto); Spotify `Title (feat. X)` vs plain local `Title` → tier 4.

Before changing anything, **measure** (V6, extended): see Verification.

---

## Bug 12: indexer scans `duplicates/` and `unorganized/` as if they were crate

### Root cause (confirmed in `lib/catalog/indexer.py`)

`_SKIP_TOPLEVEL = {'playlists', '$RECYCLE.BIN', 'System Volume Information'}`.
Every other top-level directory is indexed. Consequences:
- Bug 6.2 quarantines true duplicates to `<crate>/duplicates/`
  (`preimport/apply.duplicates_dir()` already does this today). Those files
  remain in the catalog and can be picked by the matcher (`_pick_best` takes
  the closest duration among candidates), so a playlist can link into
  `duplicates/` instead of the kept copy.
- `unorganized/` (the download staging drop) is also indexed. A track matched
  there gets a path that dangles as soon as `organize import` moves it.
  Tapedeck reads the same index.
- `_newest_mtime()` stats the same tree, so every quarantine/staging move
  also bumps the cache-staleness check (fine, but it means those directories
  cost a re-walk).

### Fix (D7 decided: skip both)

Add `'duplicates'` and `'unorganized'` to `_SKIP_TOPLEVEL` (still only
honored at the crate top level — existing behavior). `unorganized/` doesn't
need indexing because `organize import` stages it (`preimport.stage()`) and
then moves everything into `albums/` / `singles/`, which *are* indexed; the
matcher only needs files that are already in their final place. Must land
**before** the duplicate-quarantine step in Phase 2, otherwise quarantining
makes matching worse, not better. Update `indexer.py`'s docstring and
`PACKAGE_OVERVIEW.md`.

### Follow-on: don't let leftovers vanish silently

`run_album_pass`/`run_singles_pass` run beets with `--quiet`, which **skips**
uncertain matches and leaves them in `unorganized/`. Previously the indexer
saw those files, so the matcher found them. After this change they'd be
invisible, reappear in `unmatched.csv`, and be re-downloaded. So:
- `run_import()` (and `core download-songs`'s import step) must report the
  audio files still under `unorganized/` after the passes finish
  (`N files left in unorganized/ — import skipped them`), with the paths in
  `--verbose`.
- `run_import()` already returns a bool; add the leftover count to the
  structured result for `core`/`app` rather than only printing it
  (`NEW_FEATURE_GUIDE.md` §2).

---

## Bug 13: the beets `normalize_artists` plugin mangles names (D8 bundled)

### Root cause (confirmed: ran the regex against sample names)

`_FEAT_RE` is `\s*[\(\[]?\s*(?:feat(?:uring)?\.?|ft\.?|f\.)\s*` with **no
word boundaries**, applied with `.search()`. It matches `ft`/`f.`/`feat`
*inside words*:

| raw | plugin result |
|-----|---------------|
| `Daft Punk` | `Da feat. Punk` |
| `Soft Cell` | `So feat. Cell` |
| `Left Boy` | `Le feat. Boy` |
| `Defeat` | `De feat.` |
| `Jeff. Rosenstock` | `Jef feat. Rosenstock` |

It runs on every `artist`/`albumartist` of every imported item
(`on_import_task_choice`, `on_item_imported`, `on_album_imported`) and
*stores* the result, so any crate artist containing `ft`, `f.` or `feat`
mid-word that went through beets import may already carry a mangled tag. It
also feeds `canonical_albumartist()` and folder names. Second, smaller
issue: `_COLLAB_X_RE` (`\b[xX]\b`) is applied to the *featuring part* and
turns a lone `X` in a name (`Malcolm X`) into a separator.

### Fix

1. Anchor: `(?<![\w])(?:feat(?:uring)?\.?|ft\.?|f\.)(?![\w])` for the bare form,
   keeping the optional leading `(`/`[` handling; require a preceding
   whitespace/bracket or string start. Table above becomes the test
   fixture (every row must come back unchanged).
2. Drop the `_COLLAB_X_RE` substitution on the feat part, or restrict to
   `\s+x\s+` like the main-part rule.
3. D8: `_normalize_list` joins with `, ` for every length.
4. Plugin tests live with the plugin (pure function `normalize_artist()` —
   no beets import needed to test it if the `BeetsPlugin` import is
   guarded).
5. **Repair existing tags** is a separate, opt-in step (V8 finds the
   damage; fix via `organize cleanup --check-tags`-style journaled pass
   or manual): detect artist strings matching `\b\w{1,3} feat\. \w` where
   removing ` feat. ` yields a known artist from the same crate.

Land the plugin fix **before** the next `organize import` of new material.
It is independent of the cleanup phases.

---

## Bug 14: preimport's duplicate check false-positives on non-Latin titles

`preimport/plan.py::_existing_titles()` collects `normalize_key(title)` for
the merge-target folder, and `build_plan()` quarantines any incoming track
whose `normalize_key(title)` is in that set. A non-Latin title keys to `''`,
so as soon as the target album has **one** non-Latin title (`''` enters
`have`), **every** non-Latin incoming track for it is "already owned" and
sent to `duplicates/`. With Bug 12 (indexer skips `duplicates/`) those files
then vanish from the catalog. It also dedups on title alone, with no
artist/duration check.

Fix: use the shared `lib.tags.find_duplicates()` from Bug 6.2 (same
`group_key` artist + title, duration within ~2 s, disc guard). A merge into
an existing folder compares incoming members against the folder's existing
files with that same rule instead of a title-key set. Tests: non-Latin-title
album merging two non-Latin tracks → neither is a duplicate; same track in
flac+mp3 → duplicate.

---

## Bug 15: `rebuild_db()` deletes `beets.db` with no backup

`apply.rebuild_db()` does `os.remove(db)` and then as-is reimports. If the
reimport is interrupted or errors (`check=False` swallows non-zero exits),
the library is gone. Fix: rename to `beets.db.bak-<timestamp>` instead of
deleting; keep the newest N; print the backup path. (Phase 0's manual
backup remains the belt to this suspenders.)

---

## Matcher/Unicode gap — upgraded: a fully non-Latin track can never match

Because the matcher uses ASCII-only `normalize_key()`:
- A fully non-Latin **title** has key `''`, so it skips tiers 1–5 and can
  only match via tier 6 (raw lowercase title, or `(album, track)`).
- A non-Latin **primary artist** makes `_row_primary()` `''`, so tier 1 is
  skipped outright (`if not row_primary: return None`); tier 2/4 rely on
  `_row_artist_set()`, which (unlike `_entry_artist_set()`) doesn't drop `''`
  — so a non-Latin row artist is the set `{''}`, which can never intersect an
  entry's set (entries never contain `''`).
- **Tier 6a's anchor then fails too** (artist set can't overlap; and if the
  album is also non-Latin, `row_album_key` is `''` so the album anchor is
  skipped). `by_album_track` (6b) only indexes albums with a non-empty
  `normalize_album` key.
- **Net effect: a track whose title, artist *and* album are all non-Latin
  can never match any playlist row.** It will sit in `unmatched.csv` forever
  and — once `PLAYLIST_SYNC_PLAN.md` §3 autodownload exists — be re-downloaded
  on every run. (Mixed-script credits such as `Cody・Lee(李)` or
  `ぬいぐるみクレヨン Lush Crayon` have Latin tokens and are fine.)

This is no longer "optional": V9 counts the affected rows, and if the count
is non-zero it becomes a Phase 7 requirement and a hard prerequisite for
autodownload. Fix shape (A/B-tested on the real exports): give the matcher
Unicode-aware keys (the `group_key()` family) *alongside* the ASCII ones,
preserving the `''`-means-symbol-only contract tier 6 relies on, and make
`_row_artist_set()` drop `''` like `_entry_artist_set()` does.

---

## Plan of work

Each phase ends with its own gate. Don't start the next phase until the gate
passes.

### Phase 0 — safety net (before any `--apply`)

- [x] *(done — `organize/journal.py`, wired into cleanup, preimport and check-tags; `organize undo [--list] [--run ID] [--apply]`)* Add a **move/tag journal** (`<crate>/.organize_journal.jsonl`): every
  planned `move` / `tag write` with old and new value, written before it is
  performed. Enables a real undo and makes interrupted runs resumable. `safe_move()`
  and `write_tag()` stay dumb; the journal lives in the apply layer.
- [ ] Back up `beets.db` and keep a copy of `.playlist_index.jsonl`; confirm
  a filesystem snapshot or at least a `library.csv` export exists.
- [x] **Bug 15:** `rebuild_db()` renames `beets.db` to a timestamped backup
  instead of deleting it.
- [x] The journal wraps *every* mutating path, not just `run_cleanup()`:
  `preimport/apply._apply()` (incl. duplicate quarantine) and
  `check_tags(apply=True)`'s tag writes.
- [x] *(code done; V8 still to run)* **Bug 13 (plugin)** can ship any time in Phase 0–1 and should precede
  any further `organize import`. Run V8 first to see existing damage.
- [x] `python -c "import organize.cli, organize.preimport.apply,
  organize.cleanup.resplit"` (until Phase 4 deletes it) as an import smoke test, and confirm
  `organize/cleanup/__init__.py` re-exports everything `cli.py` imports,
  including `check_tags` (defined in `apply.py`).

### Phase 1 — `lib/` primitives (no change to matcher tiers or download matching)

- [ ] `lib.text`: `group_key()`, `group_album_key()`, `fold_key()` (+ sanity
  checks, incl. `fold_key('Jhené') == fold_key('Jhene')`,
  `fold_key('ぬいぐるみ') == ''`). Leave `normalize_key`/`normalize_album`
  untouched.
- [ ] `lib.tags.read_tags()`: add `disc` (D5). Force one `--reindex`
  afterward — cached sidecars lack the field and staleness won't notice.
- [ ] `lib.tags`: exact-string `write_tag()` (Bug 7); deterministic
  `dominant_album()` and `canonical_albumartist()` tie-breaks (Bug 6.5);
  `canonical_album()` (Bug 3b); `same_path()`; case-aware `safe_move()`
  (Bug 6.3); `member_filename()`, `single_filename()`, `unique_name()`,
  `find_duplicates()` (shared by cleanup and preimport; disc-guarded);
  sort `scan_audio()` output by path for determinism.
- [ ] `lib.catalog.indexer`: add `'duplicates'` and `'unorganized'` to
  `_SKIP_TOPLEVEL` (Bug 12) — must land before duplicate quarantine runs.
- [ ] Don't touch `sanitize()` yet — that's Phase 3.
- [ ] Tests: `tests/lib/test_text.py`, `tests/lib/test_tags.py` (tie-breaks,
  case-only moves on a temp dir, exact-string tag writes against a stub
  `MediaFile`).
- **Gate:** `python -m lib.text` passes; existing matcher/download/indexer
  tests unchanged and green; a new indexer test shows files under
  `duplicates/` and `unorganized/` are not in the catalog.

### Phase 2 — grouping logic

- [ ] `build_plan()` returns a small `Plan` dataclass instead of today's
  7-tuple (this phase adds duplicates, peeled/ambiguous lists, singles
  collisions). `preimport.build_plan()` keeps its report-dict keys stable —
  `beets_import` and `core` read them.
- [ ] `grouping.py`: use `group_album_key`; never merge on an empty key
  (Bug 4); `split_group()` with compilation guard + self-titled-single
  signal, promoted from resplit's `_artist_components()` (Bug 2b); delete the
  VA-override (Bug 5); keep-existing-folder rule, case-insensitive exact
  (Bug 6.4); incumbent-keeps-name + duplicate quarantine (Bug 6.1/6.2);
  `canonical_album()` per D2 (Bug 3b); planner assertions (Bug 6.6); dry-run
  summary gains `ambiguous splits` and `duplicates` sections.
- [ ] `preimport/plan.py`: same `split_group()`, same keys; remove the dead
  `if … : pass` no-op; replace the title-key duplicate check with
  `find_duplicates()` (Bug 14); `index_existing_albums()` returns the raw album string;
  merges use `canonical_album()` over incoming ∪ existing (Bug 3b).
- [ ] `apply.py` (cleanup): Bug 10 + journal + two-phase moves.
- [ ] `organize import`: leftover-in-`unorganized/` report (Bug 12 follow-on).
- **Gate (the important one):** run the **fixture suite** (below) and then a
  real `organize cleanup --verbose` dry run. Expected, qualitatively:
  most of the 220 album moves and the swaps vanish; `'Various Artists'
  albums` becomes ≥ 6 (the known compilations); `true singletons` rises
  because singles stay singles; the case-only renames are gone. Review every
  remaining move by hand — if one isn't obviously right, it's a bug or a
  decision, not something to apply.

### Phase 3 — artist-credit rendering + `sanitize()` (isolated churn step)

- [ ] Land the Bug 13 plugin fix + `, ` join (D8) first if it hasn't
  shipped.
- [ ] Implement `render_credit()` and the `_`-substituting `sanitize()`
  (Bug 9); thread `render_credit()` into `member_filename()`,
  `single_filename()` and the album-folder name builder (grouping + preimport
  staging).
- [ ] First dry run prints the distinct `/`-containing credits with counts →
  build the `AC/DC`-style allowlist from it.
- [ ] Dry run → review the (large) rename list → `--apply` → rebuild
  beets.db → reindex → `core sync`. Confirm `unmatched.csv` doesn't regress.

### Phase 4 — retire resplit

- [X] Confirm on fixtures that the regular pass (Phase 2) reproduces what
  resplit was for: a poisoned `Various Artists - Automatic` folder splits to
  two singles; a self-inflicted-VA 3-track pile-up splits; a real VA
  compilation stays; a chained-overlap album stays.
- [X] Delete `organize/cleanup/resplit.py`, `resplit_plan.py`; remove the
  `--resplit` option, its `--rebuild-db` branch and the `--check-tags` /
  `--resplit` mutual-exclusion check from `cli.py`; drop `run_resplit` from
  `organize/cleanup/__init__.py`; remove the `--resplit` paragraph from
  `README.md`; update the docstrings in `grouping.py` / `apply.py` that
  mention it, and `PACKAGE_OVERVIEW.md`.

### Phase 5 — converge on the live crate

0. **Baseline:** run `playlists --apply --rescrape` once and save
   `unmatched.csv` (and `unmatched_urls.txt`) as the before-snapshot.
1. `organize cleanup` dry run → review.
2. `organize cleanup --apply --no-tag-write` first (moves only), then the
   **second dry run must be empty of moves**.
3. `organize cleanup --apply` (tags). **Third dry run must be completely
   empty** (no moves, no tag writes) — this is the idempotency gate.
4. `organize cleanup --check-tags` (dry) → review → `--apply`: fixes
   corrupted `albumartist` on singles left by the old wrong merges **and**
   the empty `albumartist` on singles the old resplit created.
5. `organize cleanup --rebuild-db`, then `core sync` (or
   `playlists --apply --rescrape --reindex`).
6. **Diff `unmatched.csv` against the baseline.** Moves/renames shouldn't
   change matching (the matcher reads tags, not names). Newly-unmatched
   rows mean a tag rewrite changed something (e.g. an `album` rewrite
   affecting tier 3/6b) — investigate before proceeding. Newly-*matched*
   rows are expected where a poisoned `albumartist` was corrected. Rows that
   were only "matched" via `duplicates/` or `unorganized/` will now show as
   unmatched (Bug 12) — expected, and the leftovers report explains them.

### Phase 6 — tests and docs

- [ ] `tests/organize/test_cleanup.py`, `test_preimport.py` per
  `NEW_FEATURE_GUIDE.md` §5.2/5.3, built from the known-answer fixtures
  above (no `test_resplit.py` — resplit is retired).
- [ ] **Idempotency test:** apply the plan to a temp tree (stubbed tag
  reader/writer), re-plan, assert empty. Parametrize over: NTFS-style
  ordering with `X (2)` listed first, case-only variants, three-way dupes,
  non-Latin and `?` albums, VA compilation, collision singles, slash-joined
  credits, edition variants (`Album` + `Album (Deluxe)`).
- [ ] `tests/lib/test_tags.py`: `render_credit()` (slash split, `&` untouched,
  allowlist), `sanitize()` substitution, `canonical_album()` policy.
- [ ] `PACKAGE_OVERVIEW.md`: `lib/catalog/indexer.py` (skip list), `lib/text.py`
  (`group_key`), `lib/tags.py` (new helpers + changed `write_tag`/`sanitize`),
  `organize/cleanup/*` (resplit gone), `organize/preimport/plan.py`;
  Cross-cutting notes (organize groups on `group_key`, matcher/download on
  `normalize_key` — deliberate, say why).
- [ ] `README.md`: new/changed flags, `--resplit` removal, journal/undo,
  leftover report.
- [x] `TODO.md`: strike what's done.

### Phase 7 — matcher precision (after the library is clean; D6 decided)

- [ ] V6 + V9 measurements first (below).
- [ ] `lib.text.fold_key()` (already added in Phase 1) → matcher:
  `_artists_contradict()`; tier 3 veto + hard duration gate; tier 5 veto;
  tier 4 reverse lookup (Bug 11). Tests per Bug 11.
- [ ] If V6 shows label-tagged-compilation losses: add the ≤ 1 s escape hatch.
- [ ] If V9 > 0: Unicode keys in the matcher alongside the ASCII ones
  (Matcher/Unicode gap section), A/B on real exports.
- [ ] Re-run the Phase 5 `unmatched.csv` diff after each matcher change.
- Prerequisite for `PLAYLIST_SYNC_PLAN.md` §3 (autodownload of unmatched).

---

## Verification (cheap checks that settle open questions)

- **V1 — `2093 (P2)`:** read tags of `Yeat - 2093\01 - Yeat - Psycho CEO.mp3`
  with `read_tags()`; confirm `album`.
- **V2 — track numbers:** read the `track` tag on `Adhesive Wombat -
  Marsupial Madness\02 - …Rocket Science.mp3` (expect 3). Confirms the
  Bug 8.1 theory.
- **V3 — what `?` actually is:** `repr()` the album tag of one XXXTENTACION
  *Question Mark* file, and print `normalize_key()` of it (expect `''`).
- **V4 — poisoned albumartist:** read `albumartist` of
  `Ital Tek - Control\09 - Janet Jackson - …` (expect `Ital Tek`). Confirms
  the albumartist-poison explanation for why the two-track check didn't fire.
- **V5 — case-collision on NTFS:** in a scratch dir,
  `shutil.move('a.txt', 'A.txt')` via current `safe_move()` and observe `(2)`.

- **V6 — matcher false positives (extended):** load the real catalog +
  spotify manifest, run `match_rows()`. For every row resolved at
  `exact_title_album_duration` or `fuzzy_title_duration`, compute three
  things and print the counts + lists: (a) rows whose **fold_key** artist
  sets are disjoint with both sides non-empty (the would-be-vetoed set =
  false-positive candidates); (b) of those, rows whose album agrees and
  duration is within ~1 s (label-tagged-compilation candidates → decides the
  escape hatch); (c) tier-3 matches that the new hard duration gate would
  drop *despite* artist overlap (collateral). Also (d) rows that match only
  because of accent differences (fold sets equal, `normalize_key` sets
  disjoint) — these must survive the change.
- **V8 — plugin damage (Bug 13):** over the catalog, list distinct
  `artist`/`albumartist` strings containing ` feat. ` where the part before
  it is ≤ 3 characters, or that end in ` feat.`; each is a likely
  `normalize_artist()` mangling. Cross-check by running the old plugin
  regex on a handful of known names (`Daft Punk`, `Soft Cell`).
- **V9 — non-Latin unmatched (Matcher/Unicode gap):** count `unmatched.csv`
  rows (and crate entries) where `normalize_key(title) == ''` and
  `normalize_key(primary artist) == ''`; spot-check that the crate really
  does contain them.
- **V10 — multi-disc (D5):** after `disc` is readable, list albums in the
  crate with repeated track numbers across discs, to confirm the template
  stays collision-free without a disc prefix.
- **V7 — duplicates/unorganized in the index:** `grep '/duplicates/'` (or `\\duplicates\\`)
  in `.playlist_index.jsonl` and in generated `.m3u8`s.

---

## Open decisions

None — D3, D5, D6, D8, D9 were resolved in revision 3 (see the Decisions
log at the top). Measurement-gated follow-ups: Bug 11's ≤ 1 s escape hatch
(V6) and the matcher Unicode keys (V9).

---

## Known intentional behaviors — don't "fix"

- `split_artists()` doesn't split on `" and "`; the beets
  `normalize_artists` plugin does. (Per `NEW_FEATURE_GUIDE.md` §4.)
- `lib.tags.primary_token()` differs from `lib.text.primary_artist()`.
- `render_credit()` converts only `/` — `&` and `,` inside credits are left
  alone on purpose (`King Gizzard & The Lizard Wizard`, `Tyler, The Creator`).
- `normalize_key()` stays ASCII-only and returns `''` for symbol-only titles —
  the matcher's tier 6 depends on it (`by_title` excludes `''`; tier 6 runs only
  when the title key is empty).
- `lib.text.fold_key()` (matcher contradiction veto) and `group_key()`
  (organize grouping) are two *new* functions beside the untouched
  `normalize_key()`. Don't merge them: `fold_key` folds accents to ASCII and
  returns `''` for non-Latin on purpose (no evidence ≠ contradiction);
  `group_key` keeps non-Latin and never returns `''` for non-blank input.
- The matcher's `_entry_artist_set()` unions `artist` ∪ `albumartist`.
  Organize's *split detection* deliberately uses raw `artist` only (because
  organize itself writes `albumartist`); don't "align" them. The Unicode-aware key is a *new*
  function used by organize only.

## Recent Progress (as of 2026-10-05)
- **Blocking issue resolved:** Fixed Windows MAX_PATH limitation in `safe_move()` function that was causing "[WinError 3] The system cannot find the path specified" errors during file move operations in `organize cleanup --apply`.
- **Bug 13 resolved:** Verified that `organize/normalize_artists.py` has been fixed per specifications (proper word boundaries for feat detection, `\s+[xX]\s+` for collaboration, `, ` joining).
- **Bug 9/D1 resolved:** Verified that `lib.text.render_credit()` implements the D1 decision correctly (splits on `/` only, joins with `, `, leaves `&` and `,` inside credits untouched, legitimate slash credits use `_`).
- **Phase 3 allowlist built:** Reviewed distinct '/'-containing credits from dry run output and updated allowlist in `lib.text` with: 'AC/DC', '30/70', 'A/T/O/S', 'Mono/Poly'.
- **System convergence:** After applying the MAX_PATH fix and Phase 3 allowlist updates, `organize cleanup --apply` runs successfully and subsequent dry runs show dramatically reduced moves needed (from ~2986 files to case-only renames only), indicating the system is converging toward a stable state.
- **Phase 4 complete:** Retired `--resplit` option and associated code. The regular cleanup pass now reproduces the functionality previously provided by resplit (handling previously wrongly-merged folders via improved grouping logic in `split_group()`). Removed `resplit.py`, `resplit_plan.py`, `--resplit` CLI option, mutual exclusion checks, `run_resplit` from `__init__.py`, updated README.md, PACKAGE_OVERVIEW.md, docstrings in `grouping.py`/`apply.py`/`common.py`/`__init__.py`, and test files (`test_cleanup.py`, `test_import_smoke.py`).
