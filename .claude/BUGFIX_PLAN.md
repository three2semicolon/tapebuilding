# tapebuilding — bugfix plan: playlist-match misses & wrong album merges

Two bugs, found from real syncs (not yet fixed — see `TODO.md`'s
"Fixes — planned" section for the checklist entries this expands on).

**Update after reading the real source** (`lib/text.py`, `lib/tags.py`,
`organize/cleanup.py`, `organize/preimport.py`, `lib/catalog/matcher.py`):

- **Bug 2 is now confirmed, not a hypothesis** — the grouping key really
  is album-title-only, and the tie-break really does resolve a 1-vs-1
  split silently. See §Bug 2 below for the exact lines.
- **Bug 1 is still a hypothesis** — `lib.text.split_artists()`'s
  separator regex is confirmed to exclude `;`, but the raw-tag dump you
  sent (`output.txt`) turned out to be unusable — see the note at the
  end of §Bug 1 for why, and a corrected script to re-run.

**Second update (follow-up debugging session) — Bug 1's semicolon
hypothesis is now falsified, not just unconfirmed.** The corrected raw
tag dump and a full trace against the real `lib/text.py` and
`lib/catalog/matcher.py` source show the separator regex was never the
problem. See the "Status" subsection under §Bug 1 below for what's now
believed to be the actual root cause (a stale catalog cache) and what's
still needed to confirm it. Bug 2 is unaffected by this and remains
confirmed as originally written.

---

## Bug 1: multi-artist tracks land in `unmatched.csv` despite already being in the crate

### Symptom

`playlists --apply --rescrape` (or `core sync`) writes tracks to
`unmatched.csv` that are already downloaded and tagged in the crate. On
the next `core download-songs` / `organize import` pass, those "new"
downloads land in beets' duplicates folder, since the real file already
exists — the match failure, not the download, is the actual bug.

Concrete example from `unmatched.csv`:

```
_sui47	5Dj2FudGxEaCyMpdAv4LIg	I Admit with Isaiah Kaleo	Ash Levi, Isaiah Kaleo	Vinyls and Ashtrays: Disc One	unmatched	https://open.spotify.com/track/5Dj2FudGxEaCyMpdAv4LIg
```

The matching file is already sitting in the crate at
`Ash Levi - Vinyls and Ashtrays_ Disc One/05 - Ash Levi_Isaiah Kal... .mp3`
with Explorer showing Title "I Admit with Isaiah Kaleo", Contributing
artists "Ash Levi; Isaiah Kal...", Album "Vinyls and Ashtrays: D...".

### Root-cause hypothesis (original — falsified, kept for the record)

Title matches exactly on both sides ("I Admit with Isaiah Kaleo" isn't a
`feat.`-family clause, so `lib.text.normalize_title()` doesn't touch it —
it's identical either way). The theory was that the artist side breaks
because the local tag renders (in Explorer) as `"Ash Levi; Isaiah
Kaleo"` — semicolon-separated — while `split_artists()` doesn't
recognize `;` as a separator, so the local artist set never splits and
every artist-dependent tier fails to line up.

**This is dead.** The raw tag dump (decoded from `output.txt`, which was
UTF-16 and unreadable as originally sent) shows the actual `TPE1` frame
is `'Ash Levi/Isaiah Kaleo'` — slash-joined, not semicolon-joined. The
`;` Explorer showed was purely Explorer's own display rendering of a
`/`-joined value, never what's actually stored in the tag. Both original
sub-hypotheses (a multi-value frame flattened to `;` on read, or a
literal `;` written into the tag) are falsified for this file.

A full source trace confirms the code was never broken here either:
`lib.text.split_artists()`'s regex —
`r'\s*(?:,|&|/| x | vs | feat\.?|ft\.?|featuring)\s*'` — already matches
a bare `/` with no surrounding spaces required, so
`split_artists("Ash Levi/Isaiah Kaleo")` → `["Ash Levi", "Isaiah
Kaleo"]`. Tracing the rest of the path — `lib.tags.read_tags()` (via
`mediafile.MediaFile`, no multi-value TPE1 to reinterpret) →
`matcher.py`'s `_entry_artist_set()` (unions split segments from
`artist`+`albumartist` → `{"ashlevi", "isaiahkaleo"}`) → Tier 1's
predicate (`row_primary in entry_artists` → `"ashlevi" in {"ashlevi",
"isaiahkaleo"}` → `True`) — shows this track *should* match on Tier 1
against the code exactly as written today, with titles byte-identical
on both sides. There's no plausible reading of the current
`split_artists()`/`_entry_artist_set()`/Tier 1 code where this specific
file fails to match.

### Status: confirmed — the catalog cache has no automatic invalidation

`lib/catalog/indexer.py` is now in hand, and it confirms the staleness
theory directly — this is no longer a hypothesis. `get_index()`'s
caching logic is:

```python
if not reindex and os.path.exists(sidecar):
    cached = load_index(sidecar)
    if cached is not None:
        print(f"using cached index ({len(cached)} tracks) at {sidecar}")
        return cached
print(f"building index from {library_root} ...")
index = build_index(library_root, verbose=verbose)
```

There is **no mtime check, no timestamp comparison, no signal of any
kind** that the crate has changed since `.playlist_index.jsonl` was last
written. The cache is trusted unconditionally as long as the sidecar
file exists and parses — the *only* two ways it ever gets rebuilt are
(a) the sidecar is missing or corrupt, or (b) `--reindex` is passed
explicitly on that run. A file added to the crate after the last index
build simply isn't in the cache, and stays invisible to every matcher
tier until someone remembers to pass `--reindex` — exactly the failure
mode "I Admit with Isaiah Kaleo" shows. `playlists/cli.py` does expose
`--reindex` as a real flag threaded through to `build_playlists()`, so
the mechanism to force a rebuild exists; it's just opt-in with nothing
prompting you to opt in when it matters.

This also matches the file's own docstring intent — "the sidecar makes
subsequent runs instant" — the caching is a deliberate speed
optimization for a walk that "takes a couple of minutes cold" on a 10k-
track crate; it was just never paired with an invalidation strategy.

### Confirmed for this instance

Verified by running `playlists --apply --rescrape --reindex`: "I Admit
with Isaiah Kaleo" is no longer in `unmatched.csv` after a forced
reindex. Total unmatched count also dropped noticeably (~300 tracks) on
the same run — consistent with a backlog of downloads that had
accumulated in the crate across several `download spotify` runs without
an intervening `--reindex`, all invisible to the matcher until this run
forced a rebuild. Bug 1 is closed as a diagnosis; what's left is
deciding the actual fix (see "Fix" below) — the caching-with-no-
invalidation design is confirmed as the root cause, this isn't "maybe
something else is also going on."

### Decision: which fix, of three options

Confirming the root cause raises a real design choice rather than a
single obvious fix — three ways to close this, in order of how much
code changes:

1. **Do nothing, just remember `--reindex`.** Rejected — this is
   exactly the failure mode that produced the bug. Relying on manual
   discipline to run an extra flag after every download session is
   fragile by construction; it already silently failed for ~300 tracks
   across several `download spotify` runs before anyone noticed via
   `unmatched.csv`, not via anything that would have flagged the
   staleness itself.
2. **Make `--reindex` the default (always rebuild).** Simple, but
   throws away the entire point of the cache — `build_index()`'s own
   docstring notes a cold walk takes "a couple of minutes" on a 10k-
   track crate, and that cost would then hit *every* run, including
   quick dry-run previews (`playlists --playlist "_obs"` with no
   `--apply`) that currently return instantly. Not recommended as the
   primary fix, though it's a reasonable stopgap if the auto-
   invalidation work below is deferred.
3. **Recommended: automatic invalidation.** Keep the cache, but stop
   trusting it unconditionally — give `get_index()` a real signal for
   "has the crate changed since this sidecar was written" and only
   rebuild when it has. This preserves the "instant on a clean run"
   property while removing the manual step entirely. `--reindex` stays
   available as an explicit override (forcing a rebuild is still
   occasionally useful, e.g. if the sidecar itself is suspected corrupt
   without actually failing to parse).

### Fix (implementing option 3) — implemented

Implemented in an updated `lib/catalog/indexer.py`:

1. `_newest_mtime()` — a stat-only walk of the same tree `build_index()`
   covers (directories *and* files, `os.stat()` only, no `read_tags()`)
   returning the newest mtime seen. Directories are stat'd too, not just
   files, so a *deleted* file — which leaves no mtime of its own — still
   invalidates the cache via its parent directory's mtime bumping on
   removal.
2. `_is_stale(sidecar, library_root)` — compares that newest mtime
   against the sidecar's own `os.path.getmtime()`. Fails safe in both
   directions: a sidecar that vanishes mid-check counts as stale (forces
   a rebuild rather than serving something no longer readable), while a
   `library_root` that can't be stat'd at all (permissions, a removable
   drive that dropped) counts as *not* stale, so a transient filesystem
   hiccup doesn't force an unwanted multi-minute reindex — it just
   serves the existing cache for that run.
3. `get_index()` now calls `_is_stale()` before trusting an existing
   sidecar, instead of trusting it unconditionally. `--reindex` is
   unchanged as an explicit override.
4. **Tested** (stub `lib.paths`/`lib.tags`, a throwaway crate dir): built
   an index, added a file, called `get_index()` again with
   `reindex=False` — the new file was picked up automatically. Re-ran
   with nothing changed — served the cache, no rebuild. Deleted a file
   and re-ran — rebuild triggered, deletion reflected. All three cases
   behave as intended.

**Not done as part of this fix** (kept in mind, not implemented):
`lib/text.py`/`lib/tags.py` are untouched, per the "leave the separator
regex alone" note below — this bug never needed a change there. A
regression test formalizing the three cases above (add/no-change/delete)
still needs to be added to the actual test suite — the check above was a
standalone script against stub modules, not a `tests/` addition.

### Fix plan (superseded — kept for context on the reasoning)

The original plan proposed exactly what got implemented above (a
stat-only mtime check gating the cache), plus two other notes worth
keeping:

- **Regression test still owed:** the standalone script used to verify
  the fix (see above) should be turned into a real `tests/` case per
  `NEW_FEATURE_GUIDE.md` §5.2/5.3 — add/no-change/delete, same three
  cases.
- **`lib/text.py`/`lib/tags.py` were correctly left alone** — the
  separator regex was never the problem, confirmed independently
  earlier in this doc. Don't add `;` to the separator set; there's no
  evidence any real tag in the crate needs it.

### What's still open

- ~~Wire the regression test above into the actual `tests/` suite.~~
  Done — `tests/lib/catalog/test_indexer.py` now covers add/delete/
  unchanged-crate cases, plus a direct assertion (via monkeypatching
  `build_index`) that the rebuild is/isn't actually triggered rather
  than just checking the output looks right. One existing test in that
  file was asserting the *old* buggy behavior outright (`len(index) ==
  1` after adding a file, labeled "stale on purpose") — that's fixed to
  assert the corrected behavior instead, with a note in its docstring
  explaining why it changed.
- `PACKAGE_OVERVIEW.md`'s `lib/catalog/indexer.py` description still
  needs updating per `NEW_FEATURE_GUIDE.md` §5.4 — not done yet, since
  that file hasn't actually been provided in this conversation despite
  being referenced throughout (`README.md`'s "see PACKAGE_OVERVIEW.md
  for current state" line, `NEW_FEATURE_GUIDE.md`'s whole framing
  around it, etc.). Upload it and this can be closed out too.

---

## Bug 2: unrelated same-titled singles collapsed into one album folder

### Symptom

`Ash Levi - Vinyls and Ashtrays_ Disc One` shows real Ash Levi tracks
with different featured artists per track — expected, that's one
artist's actual album.

`Anysia Kym - Automatic`, by contrast, contains two files that have
nothing to do with each other beyond sharing a name:

- `01 - Anysia Kym_To...` — Title "Automatic", Contributing artists
  "Anysia Kym; Tony …", Album "Automatic"
- `01 - Spencer. - Auto…` — Title "Automatic", Contributing artists
  "Spencer.", Album "Automatic"

Both are almost certainly **singles** whose Spotify "album" field just
equals the track title (a very common single-release pattern) — two
different artists happened to title their single the same thing, and
they got merged into one folder as if they were the same release.

### Root-cause hypothesis

Per `PACKAGE_OVERVIEW.md`, album grouping happens in two places:

- `organize.preimport.stage()`'s "merge into an existing crate album
  folder" decision
- `organize.cleanup.group_files()`'s bucketing for the regroup-in-place
  pass

Both are described as keying off the album name (normalized). Neither
description mentions an artist component in the grouping key itself —
`index_existing_albums()`'s collision detection only fires when **two
existing folders** share a key (refusing *that* merge as ambiguous); it
doesn't stop a **new** incoming group of files from merging together in
the first place when their artists disagree, because artist isn't part
of what's being compared at that step.

So: `(normalized_album_title)` alone as the grouping key means any two
singles with the literal same title-as-album collide, regardless of
artist. `cleanup.py`'s "flags... VA-filed albums... in the dry-run
summary for manual review" is the closest existing guard, but per its
description that's a *warning*, not something that gates the merge
itself.

### Fix

1. Change the grouping key everywhere albums get bucketed — both
   `organize.preimport.stage()`'s incoming-file grouping and
   `organize.cleanup.group_files()` — from `(normalized_album,)` to
   `(normalized_album, normalized_albumartist_or_primary_artist)`. Two
   tracks only group into the same folder if **both** agree.
2. Real multi-artist compilations still need to merge, so this can't
   just be "artists must match exactly":
   - If tags explicitly carry a `Various Artists`/`VA` albumartist,
     treat that as an intentional compilation signal and merge as
     today.
   - Otherwise, a 2-track "album" with two artists that share **no**
     token at all is almost certainly two unrelated singles, not a
     compilation — default to **not** merging rather than merging and
     flagging. Reserve the existing "flag for manual review" behavior
     for the genuinely ambiguous middle case (3+ tracks, some artist
     overlap, unclear whether it's a real collab album or an accidental
     collision) rather than for the clear-cut case this bug actually is.
3. Update the dry-run summary language to distinguish "merged as
   before" from "would have merged, split because artists share no
   token" so a `--verbose` run makes the new behavior visible instead of
   silently changing outcomes.

### Cleanup / rebuild enhancement (fixes what's already wrong on disk)

The grouping-key fix above only prevents *new* bad merges — it does
nothing for the `Anysia Kym - Automatic` folder that already exists.
This is the "cleanup process so I can cleanup and rebuild my db with
things in the corrected locations" ask:

- Add a resplit capability to `organize cleanup` — either a new
  `--resplit` flag or folded into the existing `--apply` pass (decide
  based on how invasive you want a default `cleanup --apply` run to be;
  recommend a separate `--resplit` flag so it's opt-in the first time
  you run it against a crate that's had bad merges for a while).
- Mechanism: walk every existing album folder, recompute the (now
  artist-aware) grouping key from current file tags. Any folder whose
  contents would now split into ≥2 groups under the corrected key gets
  those files moved out into their own corrected folder(s) — named per
  the same (also-fixed) canonical-albumartist logic already in
  `lib.tags`.
- Dry-run by default, `--apply` to actually move files, matching every
  other command's convention in this repo. Follow with `--rebuild-db`
  (already exists) so beets' database matches the corrected layout.
- After a resplit, the crate catalog (`lib.catalog.indexer`) needs
  `--reindex` and playlists need a rebuild (`playlists --apply
  --rescrape` or `core sync`) before assuming Bug 1's fix alone
  explains a clean `unmatched.csv` — a resplit changes file paths, which
  changes what the index has cached.
- **Scope note on "fix formatting issues across the board":** keep this
  addition to what cleanup already owns — regrouping + tag-driven
  renames — rather than turning it into a general "fix all formatting"
  pass. If there's a separate, concrete formatting inconsistency you
  want handled (casing, `feat.` vs `with` vs `x` conventions, etc.),
  that's worth its own explicitly-scoped follow-up per
  `NEW_FEATURE_GUIDE.md`'s "decide what 'everything' means before
  building it" spirit, rather than bundling an open-ended cleanup into
  this fix.

### What I need from you to implement this precisely

- `organize/preimport.py` (specifically `stage()`'s merge decision and
  `index_existing_albums()`)
- `organize/cleanup.py` (specifically `group_files()`/`build_plan()`)
- `lib/tags.py` (`canonical_albumartist()`, since the resplit's renaming
  needs to reuse it, not reinvent it)
- One or two more examples of a wrongly-merged folder, if you have any,
  to confirm this is specifically the "single-titled-as-its-own-album"
  pattern and not something broader (e.g. genuine multi-disc albums
  getting split apart, which would need the opposite fix).