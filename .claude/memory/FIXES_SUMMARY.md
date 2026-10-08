# Fixes Summary

This document summarizes the fixes made to resolve the issues reported by the user:

## Issues Reported

1. **SoundCloud playlist names being set to URL instead of actual name**
   - User reported: "the playlist_name in playlist_tracks from the export process is being set at the url instead of the playlists actual name"

2. **Unmatched CSV files going to wrong directory**
   - User reported: "still seeing it output to /unmatched.csv instead of to soundcloud/unmatched.csv"
   - User reported: "spotify run (default too) shouild output to spotify/unmatched.csv"

## Root Causes

### Issue 1: SoundCloud Playlist Names
In `src/download/soundcloud/soundcloud_export.py`:
- The `create_playlist_format_files` function was using the set identifier (URL/ID) as the playlist name instead of the actual set name
- The `export_sets` function was not collecting actual set names when processing multiple sets

### Issue 2: Unmatched CSV Directory
In `src/playlists/build.py`:
- The `_write_unmatched` function was being called with the base exports directory instead of the service-specific directory
- Status messages were showing the incorrect paths for unmatched files

## Fixes Applied

### 1. Fixed SoundCloud Playlist Names (`src/download/soundcloud/soundcloud_export.py`)

**Modified `create_playlist_format_files` function:**
- Added optional `set_names` parameter
- Updated function to use actual set names when available, falling back to set identifier only when necessary
- Modified function to accept set names mapping and use it for playlist names

**Updated `export_sets` function:**
- Added collection of actual set names during processing
- Modified to call `_extract_info` for each set identifier to get the actual set name
- Passed the set names mapping to `create_playlist_format_files`

### 2. Fixed Unmatched CSV Directory (`src/playlists/build.py`)

**Modified `build_playlists` function:**
- Added logic to determine service-specific exports directory based on service parameter
- For soundcloud: `service_exports_dir = os.path.join(exports_dir_resolved, 'soundcloud')`
- For spotify (default): `service_exports_dir = os.path.join(exports_dir_resolved, 'spotify')`
- Updated `_write_unmatched` call to use `service_exports_dir` instead of `exports_dir_resolved`
- Added directory creation for service-specific exports directory
- Updated status messages to show correct service-specific paths

### 3. Updated Tests

**SoundCloud Export Tests (`tests/download/test_soundcloud_export.py`):**
- Updated `TestExportSpecificSet` to check for files in soundcloud subdirectory
- Updated `TestExportSets` to:
  - Check for manifest files in soundcloud subdirectory
  - Properly mock `_extract_info` to avoid network calls
  - Verify correct file paths and contents

**Spotify Export Tests (`tests/download/test_spotify_export.py`):**
- Updated `TestExportSpecificPlaylists` to check for files in spotify subdirectory
- Updated `TestExportSpecificPlaylists.test_sanitizes_playlist_name_for_filename` to check for files in spotify subdirectory
- Updated `TestExportSpecificPlaylists.test_per_playlist_txt_includes_a_blank_line_for_tracks_without_a_url` to check for files in spotify subdirectory
- Updated `TestExportPlaylists.test_writes_scoped_manifest_filenames_not_full_library_ones` to check for files in spotify subdirectory
- Updated `TestExportPlaylists.test_does_not_clobber_a_pre_existing_full_library_export` to:
  - Create prerequisite files in spotify subdirectory
  - Verify pre-existing files remain unchanged
  - Verify scoped manifest files are created in spotify subdirectory
- Updated `TestExportManifest.test_manifest_merges_a_track_shared_across_playlists_into_one_row` to check for files in spotify subdirectory
- Updated `TestExportAllData.test_writes_full_library_filenames_not_scoped_ones` to check for files in spotify subdirectory
- Updated `TestExportAllData.test_my_playlists_only_filters_by_current_user_id` to check for files in spotify subdirectory

**Playlists Build Tests (`tests/playlists/test_build.py`):**
- Updated `TestBuildPlaylistsOrchestration.test_apply_writes_m3u8_only_for_playlists_with_matches` to check for unmatched files in service-specific directory
- Updated `TestBuildPlaylistsOrchestration.test_exclude_names_skips_excluded_playlists` to check for unmatched files in service-specific directory

## Verification

All tests pass, confirming that:
1. SoundCloud playlist names now use actual set names instead of URLs/identifiers
2. Unmatched CSV files are correctly placed in service-specific directories:
   - SoundCloud: `exports/soundcloud/unmatched.csv`
   - Spotify: `exports/spotify/unmatched.csv`
3. Existing functionality remains intact
4. No regressions were introduced

## Example Usage

After these fixes, running:
```
uv run playlists --apply --reindex --archive-path Y:/music/crate --service soundcloud
```

Will now correctly:
- Use actual SoundCloud set names in playlist_tracks.csv (not URLs)
- Place unmatched files in Y:\music\crate\playlists\exports\soundcloud\unmatched.csv
- Place unmatched URLs in Y:\music\crate\playlists\exports\soundcloud\unmatched_urls.txt

Similarly for Spotify runs (default service):
- Unmatched files will go to Y:\music\crate\playlists\exports\spotify\unmatched.csv
- Unmatched URLs will go to Y:\music\crate\playlists\exports\spotify\unmatched_urls.txt