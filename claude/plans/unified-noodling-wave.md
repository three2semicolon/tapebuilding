# Plan to Fix/Implement Requested Features in tapebuilding

## Context
The user has identified several issues in their music tools tapebuilding project:
1. In process_unmatched.py: When skipping through manual fallback downloads (pressing Enter to skip), it doesn't complete the rest of the steps properly
2. They want ESC key to also work as a skip option in fallback downloads
3. The import process doesn't seem to be normalizing/formatting files correctly
4. The cleanup command outputs too much information in non-verbose mode

Additionally, the user wants to explore:
- What from the cleanup process makes sense to be pulled into the import process (preimport/import)
- Whether there's a better way to organize the normalize/cleanup/import flow

## Issues Analysis

### 1. Fallback Skip Behavior Issue
**Location**: `src/download/fallback.py`, `process_fallback()` function
**Problem**: Both user skips (empty input) and actual download failures are treated identically:
- Both are added to `fallback_failed` list
- Both cause the batch to be marked as failed (`batch_succeeded_via_fallback = False`)
- Both are logged to `soft_failures.txt` with reason 'fallback_failed'
- This makes it appear that the fallback process failed when the user intentionally skipped

**Current Code** (lines 115-118):
```python
if not user_input:
    print(f"  Skipping fallback for '{artist} - {track}'.")
    fallback_failed.append(url)
    continue
```

### 2. ESC Key Support
**Status**: Already implemented
**Location**: `src/download/fallback.py`, lines 111-113
**Code**:
```python
except (EOFError, click.exceptions.Abort):
    # Treat as empty input (skip)
    user_input = ''
```
This should already support ESC key in most terminals as it raises EOFError or click.exceptions.Abort.

### 3. Import Process Normalization
**Location**: `src/organize/beets_import.py` and related modules
**Analysis**: The import process already includes proper normalization through:
- **Pre-import staging** (`organize.preimport.stage()`): 
  - Groups files by album key (normalized albumartist + album)
  - Merges matching groups into existing crate albums (writes folder's albumartist tag)
  - Stages new album folders under `<input>/albums/` (one folder per album)
  - Writes consistent albumartist and album tags
- **Beets import** with `normalize_artists` plugin:
  - Normalizes artist strings (featuring -> feat., "x" -> ",", "and" -> ",", etc.)
  - Updates tags with MusicBrainz data
  - Applies path templates from config.yaml

**Likely Issue**: The user may be experiencing issues with specific edge cases that the cleanup process handles better, or they may not be seeing the normalization results due to timing.

### 4. Cleanup Command Verbosity
**Location**: `src/organize/cleanup/apply.py`, `run_cleanup()` function
**Problem**: Even in non-verbose mode, the function outputs:
- Detailed plan information (always shown)
- Verbose group listings (VA albums, split groups, ambiguous groups, largest album groups - always shown)
- Only the actual move details are gated behind the `verbose` flag

**Current Code** (lines 293-321):
- Lines 293-305: Basic plan summary (always shown) - acceptable
- Lines 306-321: Detailed group listings (always shown) - should be verbose-only

### 5. Cleanup vs Import Process Organization
**User Request**: Explore what from cleanup should be pulled into import process

**Analysis of Current Flow**:
- **Preimport** (`organize.preimport.stage()`): 
  - Prepares new files for Beets import
  - Groups by album key, merges with existing albums, stages new albums
  - Writes consistent baseline tags (albumartist/album)
- **Beets import** (`organize.beets_import.run_import()`):
  - Calls preimport.stage() by default (unless `--no-preimport`)
  - Runs Beets with MusicBrainz matching and normalization plugins
  - Updates tags with matched metadata, moves to final locations
- **Cleanup** (`organize.cleanup.apply()`):
  - Regroups existing crate to fix past mistakes and reorganize
  - Uses similar grouping logic but applied to entire crate
  - Handles edge cases like VA compilations, self-titled singles, ambiguous groups

**What cleanup does that could benefit preimport/import**:
1. **Advanced group resolution logic** for edge cases:
   - Self-titled singles detection (title == album)
   - VA compilation guarding (protects real compilations from being split)
   - Ambiguous group handling (>=4 members, unclear structure - kept for manual review)
   - Split group identification (same-titled but unrelated singles)
2. **Refined tag writing logic** that may handle edge cases better
3. **Consistent error handling and reporting patterns**

## Implementation Plan

### Fix 1: Improve Fallback Skip Handling
**File**: `src/download/fallback.py`
**Changes**:
1. Add a new list `fallback_skipped = []` to track intentionally skipped URLs
2. Modify skip handling to add to `fallback_skipped` instead of `fallback_failed`
3. Update batch success logic to only consider actual failures, not skips
4. Update failure reporting/logging to only include actual failures
5. Keep skip notifications for user feedback

### Fix 2: Verify ESC Key Support
**File**: `src/download/fallback.py`
**Verification**: Confirm EOFError and click.exceptions.Abort are properly caught and treated as skips (already implemented)

### Fix 3: Enhance Import Process with Cleanup-Inspired Logic
**Files**: 
- `src/organize/preimport/apply.py` (primary enhancement target)
- `src/organize/beets_import.py` (ensure proper integration)
**Changes**:
1. Consider incorporating cleanup's advanced group resolution logic into preimport:
   - Self-titled singles detection and handling
   - VA compilation guarding logic
   - Ambiguous group detection (for reporting/manual review)
   - Split group identification
2. Evaluate sharing more core grouping logic between cleanup and preimport
3. Ensure the enhancement maintains preimport's primary goal: preparing clean input for Beets

### Fix 4: Reduce Cleanup Command Verbosity
**File**: `src/organize/cleanup/apply.py`
**Function**: `run_cleanup()`
**Changes**:
1. Move the detailed group listings section (lines 306-321) inside the `if verbose:` block
2. Keep the basic plan summary (lines 293-305) visible in non-verbose mode
3. Keep the verbose move details (lines 331-339) inside the existing `if verbose:` block

## Detailed Implementation

### Fix 1: Fallback Skip Handling
In `src/download/fallback.py`:

1. Add `fallback_skipped = []` initialization near line 62
2. Change lines 115-118 from:
```python
if not user_input:
    print(f"  Skipping fallback for '{artist} - {track}'.")
    fallback_failed.append(url)
    continue
```
to:
```python
if not user_input:
    print(f"  Skipping fallback for '{artist} - {track}'.")
    fallback_skipped.append(url)
    continue
```
3. Update line 200 from:
```python
batch_succeeded_via_fallback = len(fallback_failed) == 0
```
to:
```python
batch_succeeded_via_fallback = len(fallback_failed) == 0  # Only actual failures matter
```
4. Update lines 202-208 from:
```python
if fallback_failed:
    print(f"  Fallback failed for {len(fallback_failed)} URL(s) in batch.")
    # Log the failed URLs
    _log_urls('soft_failures.txt', fallback_failed, reason='fallback_failed')
else:
    print(f"  All URLs in batch succeeded via fallback."
```
to:
```python
if fallback_failed:
    print(f"  Fallback failed for {len(fallback_failed)} URL(s) in batch.")
    # Log the failed URLs
    _log_urls('soft_failures.txt', fallback_failed, reason='fallback_failed')
elif fallback_skipped:
    print(f"  Skipped fallback for {len(fallback_skipped)} URL(s) in batch.")
else:
    print(f"  All URLs in batch succeeded via fallback."
```

### Fix 4: Reduce Cleanup Verbosity
In `src/organize/cleanup/apply.py`:

1. Move lines 306-321 (the detailed group listings) inside the `if verbose:` block that starts at line 331
2. The structure should become:
```python
# Existing code...
print()
print("=== plan ===")
# ... basic plan summary lines 293-305 ...

if verbose:
    # Moved group listings here (was lines 306-321)
    if va_groups:
        print("\n  VA albums (no single majority artist -> filed under 'Various Artists'):")
        # ... etc for all the group listings ...

    # ... existing verbose move details (lines 331-339) ...
```

### Fix 3: Enhance Import with Cleanup Logic (Conceptual)
For the preimport enhancement, consider:

**In `src/organize/preimport/apply.py`** in the `stage()` function:

1. **After group formation** (line 127: `groups = group_files(files)`) but **before plan building** (line 129: `plan_result = build_plan(...)`), consider:
   - Analyzing groups for self-titled singles characteristics
   - Applying VA compilation guarding logic to protect real compilations
   - Identifying ambiguous groups for special handling/reporting
   - Flagging split groups (same-titled but unrelated singles)

2. **Potential approaches**:
   - Option A: Import and adapt cleanup's `resolve_group()` logic for preinput-specific use
   - Option B: Share more core logic by moving common grouping functions to `lib.tags` or a new shared module
   - Option C: Enhance preimport's reporting to highlight edge cases found (without changing core behavior)

3. **Specific cleanup logic that may benefit preimport**:
   - `is_compilation_guard()` - to better identify and protect real VA compilations
   - `_is_self_titled_singles()` - to detect and specially handle self-titled singles
   - Ambiguous and split group detection - for improved reporting and manual review hints

**Important**: Any enhancement must preserve preimport's primary purpose: 
- Create clean, consistent input for Beets import
- Not over-complicate the preimport process
- Maintain compatibility with Beets' expectations

## Verification Plan

### Test Fallback Skip Fix
1. Run `uv run core process-unmatched --apply --manual`
2. When prompted for a fallback URL, press Enter to skip
3. Verify that:
   - "Skipping fallback for 'Track Name'." is shown
   - No "Fallback failed for X URL(s)" message appears (unless there are actual failures)
   - The process continues to subsequent steps (import, playlist sync)
   - Skipped URLs are not logged to soft_failures.txt

### Test ESC Key Support
1. Run fallback process
2. When prompted, press ESC key
3. Verify it behaves the same as pressing Enter (treated as skip)

### Test Import Normalization (Enhanced)
1. Run the full process: `uv run core process-unmatched --apply --manual`
2. Check that imported files in the crate have proper metadata normalization
3. Verify edge case handling:
   - VA compilations are protected from incorrect splitting
   - Self-titled singles are handled appropriately
   - Ambiguous groups are identified for review
4. Verify that files are organized correctly into albums/ and singles/ folders with proper naming

### Test Cleanup Verbosity
1. Run `uv run organize cleanup --apply` (non-verbose)
2. Verify output shows only:
   - Crate and mode info
   - Scanned files count
   - Basic plan summary (counts)
   - No detailed group listings
3. Run `uv run organize cleanup --apply --verbose`
4. Verify output includes all the detailed group listings and move details

## Files to Modify
1. `src/download/fallback.py` - Fix fallback skip handling
2. `src/organize/cleanup/apply.py` - Reduce cleanup verbosity
3. `src/organize/preimport/apply.py` - Consider enhancement with cleanup-inspired logic (to be determined)
4. (No changes needed for ESC key - already implemented)
5. (Verify import process works correctly - core normalization already present)

## Expected Outcomes
1. Skipping fallback downloads via Enter key will not be treated as failures
2. ESC key will work as a skip option (already functional)
3. Import process will properly normalize and organize files, with potential enhancements for edge case handling
4. Cleanup command will have reduced output in non-verbose mode, showing only essential information
5. Better alignment between cleanup and import processes where appropriate, reducing duplication while preserving each component's distinct purpose