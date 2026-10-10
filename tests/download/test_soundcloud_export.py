"""Tests for download.soundcloud_export - TEST_PLANS.md
'download/soundcloud_export.py' section. Written against the actual
current source.

No real yt-dlp calls are made - fake implementations are used instead.
"""
import csv
import os
from unittest import mock

import pytest

from download.soundcloud.soundcloud_export import (
    export_set,
    export_specific_set,
    export_sets,
    list_user_likes,
    list_user_sets,
    merge_and_deduplicate,
    _soundcloud_track_key,
)


class TestSoundcloudTrackKey:
    def test_track_key_uses_url_when_available(self):
        track = {
            'track_url': 'https://soundcloud.com/artist/track',
            'title': 'Track Title',
            'uploader': 'Artist Name'
        }
        key = _soundcloud_track_key(track)
        assert key == ('url', 'https://soundcloud.com/artist/track')

    def test_track_key_falls_back_to_title_uploader(self):
        track = {
            'track_url': '',  # No URL
            'title': 'Track Title',
            'uploader': 'Artist Name'
        }
        key = _soundcloud_track_key(track)
        assert key == ('fallback', 'tracktitle|artistname')

    def test_track_key_handles_empty_values(self):
        track = {
            'track_url': '',
            'title': '',
            'uploader': ''
        }
        key = _soundcloud_track_key(track)
        assert key == ('fallback', '|')  # Two empty strings normalized to empty, separated by |


class TestMergeAndDeduplicate:
    def test_merges_and_deduplicates_by_track_key(self):
        track1 = {'track_url': 'url1', 'title': 'Track 1', 'uploader': 'Artist A'}
        track2 = {'track_url': 'url2', 'title': 'Track 2', 'uploader': 'Artist B'}  # Different URL
        track3 = {'track_url': 'url1', 'title': 'Track 1', 'uploader': 'Artist A'}  # Duplicate of track1
        track4 = {'track_url': '', 'title': 'Track 3', 'uploader': 'Artist C'}  # No URL, fallback key

        result = merge_and_deduplicate([[track1, track2], [track3, track4]])

        # Should have 3 unique tracks: track1, track2, track4 (track3 is duplicate of track1)
        assert len(result) == 3
        track_urls = {t.get('track_url', '') for t in result}
        assert track_urls == {'url1', 'url2', ''}

    def test_preserves_order_of_first_appearance(self):
        track_a = {'track_url': 'url-a', 'title': 'Track A', 'uploader': 'Artist A'}
        track_b = {'track_url': 'url-b', 'title': 'Track B', 'uploader': 'Artist B'}
        track_a_duplicate = {'track_url': 'url-a', 'title': 'Track A', 'uploader': 'Artist A'}  # Duplicate

        result = merge_and_deduplicate([[track_a, track_b], [track_a_duplicate, track_b]])

        # Should be [track_a, track_b] - preserving first appearance order
        assert len(result) == 2
        assert result[0]['track_url'] == 'url-a'
        assert result[1]['track_url'] == 'url-b'


class TestListUserSets:
    def test_extracts_sets_from_yt_dlp_info(self):
        # Mock the _extract_info function to return test data
        with mock.patch('download.soundcloud.soundcloud_export._extract_info') as mock_extract:
            mock_extract.return_value = {
                'entries': [
                    {
                        'title': 'My Favorite Set',
                        'url': 'https://soundcloud.com/user/sets/favorite',
                        'track_count': 10
                    },
                    {
                        'title': 'Chill Vibes',
                        'url': 'https://soundcloud.com/user/sets/chill',
                        'track_count': 5
                    }
                ]
            }

            result = list_user_sets('https://soundcloud.com/user')
            assert len(result) == 2
            assert result[0]['name'] == 'My Favorite Set'
            assert result[0]['url'] == 'https://soundcloud.com/user/sets/favorite'
            assert result[0]['track_count'] == 10
            assert result[1]['name'] == 'Chill Vibes'
            assert result[1]['url'] == 'https://soundcloud.com/user/sets/chill'
            assert result[1]['track_count'] == 5

    def test_handles_username_input(self):
        with mock.patch('download.soundcloud.soundcloud_export._extract_info') as mock_extract:
            mock_extract.return_value = {
                'entries': [
                    {
                        'title': 'My Set',
                        'url': 'https://soundcloud.com/me/sets/myset',
                        'track_count': 3
                    }
                ]
            }

            result = list_user_sets('me')  # Username without https://
            assert len(result) == 1
            assert result[0]['name'] == 'My Set'
            # Should have normalized to full URL
            assert result[0]['url'] == 'https://soundcloud.com/me/sets/myset'


class TestListUserLikes:
    def test_extracts_likes_from_yt_dlp_info(self):
        with mock.patch('download.soundcloud.soundcloud_export._extract_info') as mock_extract:
            mock_extract.return_value = {
                'entries': [
                    {
                        'title': 'Liked Track 1',
                        'url': 'https://soundcloud.com/artist/track1'
                    },
                    {
                        'title': 'Liked Track 2',
                        'url': 'https://soundcloud.com/artist/track2'
                    }
                ]
            }

            result = list_user_likes('https://soundcloud.com/user')
            assert len(result) == 2
            assert result[0]['name'] == 'Liked Track 1'
            assert result[0]['url'] == 'https://soundcloud.com/artist/track1'
            assert result[0]['track_count'] == 1  # Each like counts as 1 track
            assert result[1]['name'] == 'Liked Track 2'
            assert result[1]['url'] == 'https://soundcloud.com/artist/track2'
            assert result[1]['track_count'] == 1

    def test_returns_empty_list_when_no_entries(self):
        with mock.patch('download.soundcloud.soundcloud_export._extract_info') as mock_extract:
            mock_extract.return_value = {'entries': []}  # Empty entries list

            result = list_user_likes('https://soundcloud.com/user')
            assert result == []


class TestExportSet:
    def test_exports_set_to_track_dicts(self):
        with mock.patch('download.soundcloud.soundcloud_export._extract_info') as mock_extract:
            mock_extract.return_value = {
                'entries': [
                    {
                        'title': 'First Track',
                        'uploader': 'Artist One',
                        'url': 'https://soundcloud.com/artist/track1'
                    },
                    {
                        'title': 'Second Track',
                        'uploader': 'Artist Two',
                        'url': 'https://soundcloud.com/artist/track2'
                    }
                ]
            }

            result = export_set('https://soundcloud.com/artist/set')
            assert len(result) == 2
            assert result[0]['title'] == 'First Track'
            assert result[0]['uploader'] == 'Artist One'
            assert result[0]['track_url'] == 'https://soundcloud.com/artist/track1'
            assert result[0]['position'] == 1
            assert result[1]['title'] == 'Second Track'
            assert result[1]['uploader'] == 'Artist Two'
            assert result[1]['track_url'] == 'https://soundcloud.com/artist/track2'
            assert result[1]['position'] == 2

    def test_returns_empty_list_on_extract_failure(self):
        with mock.patch('download.soundcloud.soundcloud_export._extract_info') as mock_extract:
            mock_extract.return_value = None  # Extraction failed

            result = export_set('https://soundcloud.com/artist/badset')
            assert result == []


class TestExportSpecificSet:
    def test_calls_export_set_and_writes_files(self, tmp_path):
        with mock.patch('download.soundcloud.soundcloud_export._extract_info') as mock_extract, \
             mock.patch('download.soundcloud.soundcloud_export.export_set') as mock_export_set:
            # Mock the set info extraction
            mock_extract.return_value = {
                'title': 'Test Set',  # This will be used to generate the filename
                'entries': []  # We don't need entries since we're mocking export_set directly
            }

            mock_export_set.return_value = [
                {'title': 'Track 1', 'uploader': 'Artist', 'track_url': 'https://soundcloud.com/artist/track1', 'position': 1}
            ]

            result = export_specific_set(
                sp=None,  # Not used for SoundCloud
                set_identifier='https://soundcloud.com/artist/set',
                export_dir=str(tmp_path)
            )

            # Should return the tracks
            assert len(result) == 1
            assert result[0]['title'] == 'Track 1'

            # Should have created the CSV and TXT files in the soundcloud subdirectory
            csv_file = tmp_path / 'soundcloud' / 'set_Test_Set.csv'  # Filename is derived from set name
            txt_file = tmp_path / 'soundcloud' / 'set_Test_Set_urls.txt'
            assert csv_file.exists()
            assert txt_file.exists()

            # Check CSV contents - read and parse it
            with open(csv_file, 'r', encoding='utf-8-sig') as f:  # Note: utf-8-sig to handle BOM
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 1
                assert rows[0]['title'] == 'Track 1'
                assert rows[0]['uploader'] == 'Artist'
                assert rows[0]['track_url'] == 'https://soundcloud.com/artist/track1'
                assert rows[0]['position'] == '1'

            # Check TXT contents
            assert txt_file.read_text(encoding='utf-8').strip() == 'https://soundcloud.com/artist/track1'


class TestExportSets:
    def test_exports_multiple_sets_and_creates_manifest(self, tmp_path):
        with mock.patch('download.soundcloud.soundcloud_export.export_specific_set') as mock_export_specific, \
             mock.patch('download.soundcloud.soundcloud_export._extract_info') as mock_extract_info:
            # Mock return values for two different sets
            mock_export_specific.side_effect = [
                [  # First set
                    {'title': 'Track A', 'uploader': 'Artist A', 'track_url': 'https://soundcloud.com/artist/tracka', 'position': 1}
                ],
                [  # Second set
                    {'title': 'Track B', 'uploader': 'Artist B', 'track_url': 'https://soundcloud.com/artist/trackb', 'position': 1},
                    {'title': 'Track A', 'uploader': 'Artist A', 'track_url': 'https://soundcloud.com/artist/tracka', 'position': 2}  # Duplicate track
                ]
            ]

            # Mock the _extract_info function to return set names
            def mock_extract_info_side_effect(url, cookies_from_browser=None):
                if 'set1' in url:
                    return {'title': 'Set One'}
                elif 'set2' in url:
                    return {'title': 'Set Two'}
                return {'title': 'Unknown Set'}

            mock_extract_info.side_effect = mock_extract_info_side_effect

            result = export_sets(
                sp=None,
                set_identifiers=['https://soundcloud.com/artist/set1', 'https://soundcloud.com/artist/set2'],
                export_dir=str(tmp_path)
            )

            # Should return deduplicated tracks (Track A should appear only once)
            assert len(result) == 2
            track_urls = {t['track_url'] for t in result}
            assert track_urls == {
                'https://soundcloud.com/artist/tracka',
                'https://soundcloud.com/artist/trackb'
            }

            # Should have created manifest files in the soundcloud subdirectory
            manifest_csv = tmp_path / 'soundcloud' / 'soundcloud_manifest.csv'
            manifest_txt = tmp_path / 'soundcloud' / 'soundcloud_manifest_urls.txt'
            assert manifest_csv.exists()
            assert manifest_txt.exists()

            # Check manifest CSV has 2 unique tracks
            with open(manifest_csv, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 2
                manifest_urls = {r['track_url'] for r in rows}
                assert manifest_urls == {
                    'https://soundcloud.com/artist/tracka',
                    'https://soundcloud.com/artist/trackb'
                }

            # Check manifest TXT has 2 URLs
            manifest_txt_lines = manifest_txt.read_text(encoding='utf-8').strip().split('\n')
            assert len(manifest_txt_lines) == 2
            assert set(manifest_txt_lines) == {
                'https://soundcloud.com/artist/tracka',
                'https://soundcloud.com/artist/trackb'
            }