# Phase 1 lib/ primitives Implementation Plan

## Context
The user has requested to complete all remaining open tasks in Phase 1 of the bugfix plan. Phase 1 focuses on implementing core library primitives in `lib/` that will be used throughout the codebase for improved tag handling, grouping logic, and deterministic behavior.

The following tasks from TODO.md need to be completed:
1. `lib.tags.write_tag()`: compare exact NFC strings, not `normalize_key`, so case-only/non-Latin fixes actually write and identical values no-op. (Bug 7)
2. `lib.tags`: deterministic tie-breaks in `dominant_album()` / `canonical_albumartist()`; `canonical_album()` (merge editions, keep the edition marker — D2); `same_path()` + case-aware `safe_move()` (two-step for case-only); shared `member_filename()` / `single_filename()` / `unique_name()`; sort `scan_audio()` output. (Bugs 3b, 6)
3. `lib.tags.read_tags()` adds `disc` (D5); force one `--reindex` after. `lib.tags.find_duplicates()` (same `group_key` artist+title, ≤ ~2 s, never across differing `disc`) shared by cleanup + preimport.
4. **Bug 12:** `lib.catalog.indexer._SKIP_TOPLEVEL` += `duplicates`, `unorganized` (D7). `unorganized/` is handled by `preimport` + `import`, which move files into `albums/`/`singles/` before they're indexed. Must land before duplicate quarantine.
5. Tests: `tests/lib/test_text.py`, `tests/lib/test_tags.py`, indexer skip-list.

## Implementation Approach

### 1. Fix lib.tags.write_tag() for Bug 7
**Location:** `src/lib/tags.py` lines 62-77
**Change:** Replace `normalize_key(current) != normalize_key(value)` comparison with exact NFC string comparison using `unicodedata.normalize('NFC', current) != unicodedata.normalize('NFC', value)`
**Reasoning:** This ensures that case-only or non-Latin differences actually trigger tag writes, while identical NFC-normalized values are treated as no-ops.

### 2. Enhance lib.tags for Bugs 3b and 6

#### A. Add deterministic tie-breaks to existing functions
- **`dominant_album()`** (lines 113-124): When there's a tie in album frequency, use alphabetical ordering of original-cased strings as tie-break
- **`canonical_albumartist()`** (lines 79-110): When there's a tie in albumartist/artist frequency, use alphabetical ordering of original-cased strings as tie-break

#### B. Add new canonical_album() function
**Location:** `src/lib/tags.py` (after `dominant_album()`)
**Purpose:** Merge edition strings while keeping edition marker (D2)
**Logic:** 
- Group files by `normalize_album()` (edition-stripped)
- For each group, if multiple edition variants exist, select the one that:
  1. Has the edition marker (from `strip_edition_suffix` comparison)
  2. If multiple have editions, choose longest/most specific edition string
  3. If none have editions, use any variant
- Return original-cased string

#### C. Add same_path() and enhance safe_move()
**Location:** `src/lib/tags.py`
**Purpose:** Case-aware path comparison and moving
**`same_path()`**: Compare paths using case-sensitive comparison on case-sensitive filesystems, case-insensitive on case-insensitive (like Windows NTFS)
**Enhanced `safe_move()`**: Two-step approach for case-only collisions:
1. First attempt to move to target path
2. If collision exists only due to case differences, use temporary intermediate path

#### D. Add shared filename functions
**Location:** `src/lib/tags.py`
**Functions to add:**
- `member_filename(track_num, artist, title, ext)`: Creates standardized filename for album tracks
- `single_filename(artist, title, ext)`: Creates standardized filename for singles
- `unique_name(existing_names, proposed_name)`: Generates unique name by adding (2), (3), etc. suffixes

#### E. Modify scan_audio() to sort output
**Location:** `src/lib/tags.py` lines 127-149
**Change:** Sort returned files list by (artist, album, track number, title) for deterministic ordering

### 3. Enhance lib.tags.read_tags() for D5 and add find_duplicates()
**Location:** `src/lib/tags.py`
**Changes to `read_tags()`:**
- Add 'disc' field to returned dict from MediaFile.disc
- Default to 0 or None if not present

**New function `find_duplicates()`:**
**Location:** `src/lib/tags.py`
**Purpose:** Find potential duplicate tracks
**Logic:**
- Group by (`group_key(artist)`, `group_key(title)`)
- Within each group, further sub-group by disc number
- Only consider duplicates within same disc (never across differing disc)
- Return groups with 2+ files where track times are within ~2 seconds

### 4. Fix Bug 12 in lib.catalog.indexer
**Location:** `src/lib/catalog/indexer.py` line 35
**Change:** Add 'duplicates' and 'unorganized' to `_SKIP_TOPLEVEL` set
**From:** `{'playlists', '$RECYCLE.BIN', 'System Volume Information'}`
**To:** `{'playlists', '$RECYCLE.BIN', 'System Volume Information', 'duplicates', 'unorganized'}`

### 5. Create/Update Tests
**Location:** `tests/lib/test_tags.py`
**Add test classes for:**
- TestWriteTagNFC (for Bug 7 NFC string comparison)
- TestCanonicalAlbum (for new canonical_album function)
- TestSamePath (for path comparison function)
- TestFindDuplicates (for new find_duplicates function)
- TestDiscField (for disc field in read_tags)

**Location:** `tests/lib/test_text.py`
**No changes needed** - the text.py tests were already completed in the previous work

**Verify indexer skip-list tests work** - ensure existing tests still pass with new skip dirs

## Files to Modify
1. `src/lib/tags.py` - Primary implementation location for most tasks
2. `src/lib/catalog/indexer.py` - Bug 12 fix
3. `tests/lib/test_tags.py` - Additional test coverage

## Verification Strategy
1. Run existing test suite: `python -m pytest tests/` - should still pass
2. Test specific functions with targeted unit tests
3. Verify end-to-end functionality with organize cleanup --dry-run
4. Confirm Bug 7 fix works with case-only tag differences
5. Verify deterministic behavior in grouping functions
6. Test find_duplicates() with various scenarios
7. Confirm indexer properly skips duplicates/ and unorganized/ directories

## Dependencies
- No external dependencies beyond existing codebase
- Builds upon previously completed Phase 1 lib/text.py functions (group_key, group_album_key, fold_key)