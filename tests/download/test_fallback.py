"""Tests for download.fallback - fallback logic for when primary download methods fail."""

from unittest import mock


from download.fallback import _log_urls, process_fallback


class TestLogUrls:
    def test_logs_urls_with_reason(self, tmp_path):
        log_file = tmp_path / "test_log.txt"
        urls = ["https://example.com/1", "https://example.com/2"]
        _log_urls(str(log_file), urls, reason="test_reason")

        content = log_file.read_text(encoding="utf-8")
        lines = content.strip().split('\n')
        assert len(lines) == 2
        assert "https://example.com/1  # test_reason" in lines
        assert "https://example.com/2  # test_reason" in lines

    def test_logs_urls_without_reason(self, tmp_path):
        log_file = tmp_path / "test_log.txt"
        urls = ["https://example.com/1", "https://example.com/2"]
        _log_urls(str(log_file), urls, reason=None)

        content = log_file.read_text(encoding="utf-8")
        lines = content.strip().split('\n')
        assert len(lines) == 2
        assert "https://example.com/1" in lines
        assert "https://example.com/2" in lines

    def test_appends_to_existing_file(self, tmp_path):
        log_file = tmp_path / "test_log.txt"
        log_file.write_text("existing_content\n", encoding="utf-8")

        urls = ["https://example.com/1"]
        _log_urls(str(log_file), urls, reason="test_reason")

        content = log_file.read_text(encoding="utf-8")
        assert "existing_content" in content
        assert "https://example.com/1  # test_reason" in content


class TestProcessFallback:
    def test_process_fallback_spotify_all_skip(self):
        """Test when all URLs are skipped due to missing metadata."""
        batch = ["url1", "url2"]
        metadata = {
            "url1": {"artist": "", "track": "Track 1"},  # Missing artist
            "url2": {"artist": "Artist 2", "track": ""},  # Missing track
        }

        with mock.patch('click.prompt', return_value='') as mock_prompt:
            successful, failed, batch_succeeded = process_fallback(
                batch=batch,
                metadata=metadata,
                output_dir="/tmp/output",
                format="mp3",
                overwrite_errors=False,
                cookies_from_browser=None,
                resolved_ffmpeg="/usr/bin/ffmpeg",
                library_index={},
            )

            # All should be failed due to missing metadata
            assert successful == []
            assert failed == ["url1", "url2"]
            assert batch_succeeded is False
            assert mock_prompt.call_count == 0  # No prompts should be made

    def test_process_fallback_spotify_all_exist(self):
        """Test when all URLs already exist in library."""
        batch = ["url1", "url2"]
        metadata = {
            "url1": {"artist": "Artist 1", "track": "Track 1"},
            "url2": {"artist": "Artist 2", "track": "Track 2"},
        }
        # Pre-populate library index with normalized stems
        library_index = {
            "artist1track1": True,  # normalized("Artist 1 - Track 1")
            "artist2track2": True,  # normalized("Artist 2 - Track 2")
        }

        with mock.patch('click.prompt', return_value='') as mock_prompt:
            successful, failed, batch_succeeded = process_fallback(
                batch=batch,
                metadata=metadata,
                output_dir="/tmp/output",
                format="mp3",
                overwrite_errors=False,
                cookies_from_browser=None,
                resolved_ffmpeg="/usr/bin/ffmpeg",
                library_index=library_index,
            )

            # All should be successful due to pre-existing files
            assert successful == ["url1", "url2"]
            assert failed == []
            assert batch_succeeded is True
            assert mock_prompt.call_count == 0  # No prompts should be made

    def test_process_fallback_spotify_user_provides_url(self, tmp_path):
        """Test when user provides a YouTube URL as fallback."""
        batch = ["url1"]
        metadata = {
            "url1": {"artist": "Artist 1", "track": "Track 1"},
        }
        library_index = {}  # Empty library index

        # Mock click.prompt to return a YouTube URL
        test_url = "https://www.youtube.com/watch?v=test123"

        with mock.patch('click.prompt', return_value=test_url) as mock_prompt:
            # Mock download_ytdl to return True (success)
            with mock.patch('download.fallback.download_ytdl', return_value=True) as mock_download:
                successful, failed, batch_succeeded = process_fallback(
                    batch=batch,
                    metadata=metadata,
                    output_dir=str(tmp_path),
                    format="mp3",
                    overwrite_errors=False,
                    cookies_from_browser=None,
                    resolved_ffmpeg="/usr/bin/ffmpeg",
                    library_index=library_index,
                )

                # Should be successful
                assert successful == ["url1"]
                assert failed == []
                assert batch_succeeded is True
                assert mock_prompt.call_count == 1
                mock_download.assert_called_once_with(
                    test_url,
                    output_dir=str(tmp_path),
                    audio_format="mp3",
                    audio_quality='0',
                    embed_thumbnail=True,
                    overwrite=False,
                    verbose=False,
                    metadata_only=False,
                    cookies_from_browser=None,
                    ffmpeg_path="/usr/bin/ffmpeg",
                )

    def test_process_fallback_spotify_user_provides_local_file(self, tmp_path):
        """Test when user provides a local file path as fallback."""
        batch = ["url1"]
        metadata = {
            "url1": {"artist": "Artist 1", "track": "Track 1"},
        }
        library_index = {}  # Empty library index

        # Create a temporary file to simulate user-provided local file
        source_file = tmp_path / "source.mp3"
        source_file.write_bytes(b"fake mp3 content")

        # Mock click.prompt to return the local file path
        test_path = str(source_file)

        with mock.patch('click.prompt', return_value=test_path) as mock_prompt:
            successful, failed, batch_succeeded = process_fallback(
                batch=batch,
                metadata=metadata,
                output_dir=str(tmp_path),
                format="mp3",
                overwrite_errors=False,
                cookies_from_browser=None,
                resolved_ffmpeg="/usr/bin/ffmpeg",
                library_index=library_index,
            )

            # Should be successful
            assert successful == ["url1"]
            assert failed == []
            assert batch_succeeded is True
            assert mock_prompt.call_count == 1

            # Verify the file was copied to output directory
            expected_output = tmp_path / "Artist 1 - Track 1.mp3"
            assert expected_output.exists()

    def test_process_fallback_spotify_user_skips(self):
        """Test when user skips fallback (provides empty input)."""
        batch = ["url1"]
        metadata = {
            "url1": {"artist": "Artist 1", "track": "Track 1"},
        }
        library_index = {}  # Empty library index

        # Mock click.prompt to return empty string (user skips)
        with mock.patch('click.prompt', return_value='') as mock_prompt:
            successful, failed, batch_succeeded = process_fallback(
                batch=batch,
                metadata=metadata,
                output_dir="/tmp/output",
                format="mp3",
                overwrite_errors=False,
                cookies_from_browser=None,
                resolved_ffmpeg="/usr/bin/ffmpeg",
                library_index=library_index,
            )

            # Should be failed (user skipped)
            assert successful == []
            assert failed == ["url1"]
            assert batch_succeeded is False
            assert mock_prompt.call_count == 1

    def test_process_fallback_soundcloud(self):
        """Test fallback processing for SoundCloud URLs."""
        batch = ["url1"]
        metadata = {
            "url1": {"artist": "Artist 1", "track": "Track 1"},
        }
        library_index = {}  # Empty library index

        # Mock click.prompt to return empty string (user skips)
        with mock.patch('click.prompt', return_value='') as mock_prompt:
            successful, failed, batch_succeeded = process_fallback(
                batch=batch,
                metadata=metadata,
                output_dir="/tmp/output",
                format="mp3",
                overwrite_errors=False,
                cookies_from_browser=None,
                resolved_ffmpeg="/usr/bin/ffmpeg",
                library_index=library_index,
            )

            # Should be failed (user skipped)
            assert successful == []
            assert failed == ["url1"]
            assert batch_succeeded is False
            assert mock_prompt.call_count == 1


class TestProcessFallbackLost:
    """Tests for marking tracks as lost via backspace in manual fallback."""

    def test_backspace_marks_url_as_lost(self):
        """Pressing backspace marks the URL as lost (in fallback_lost, not failed)."""
        batch = ["url1"]
        metadata = {
            "url1": {"artist": "Artist 1", "track": "Track 1"},
        }
        library_index = {}

        with mock.patch('download.fallback._read_fallback_input', return_value=('lost', None)):
            successful, failed, batch_succeeded = process_fallback(
                batch=batch,
                metadata=metadata,
                output_dir="/tmp/output",
                format="mp3",
                overwrite_errors=False,
                cookies_from_browser=None,
                resolved_ffmpeg="/usr/bin/ffmpeg",
                library_index=library_index,
            )

            assert successful == []
            assert failed == []  # lost is intentional, not a failure
            assert batch_succeeded is False

    def test_backspace_writes_to_lost_songs_csv(self, tmp_path):
        """Pressing backspace appends the song's row to lost-songs.csv."""
        unmatched_csv = tmp_path / "unmatched.csv"
        unmatched_csv.write_text(
            "playlist_name,track_id,track_name,artist_names,album_name,tier_tried,spotify_url\n"
            "My Playlist,track123,Track One,Artist One,Album One,tier3,https://open.spotify.com/track/url1\n",
            encoding="utf-8-sig",
        )

        batch = ["https://open.spotify.com/track/url1"]
        metadata = {
            "https://open.spotify.com/track/url1": {"artist": "Artist One", "track": "Track One"},
        }
        library_index = {}

        lost_songs_path = tmp_path / "lost-songs.csv"

        with mock.patch('download.fallback._read_fallback_input', return_value=('lost', None)):
            successful, failed, batch_succeeded = process_fallback(
                batch=batch,
                metadata=metadata,
                output_dir=str(tmp_path),
                format="mp3",
                overwrite_errors=False,
                cookies_from_browser=None,
                resolved_ffmpeg="/usr/bin/ffmpeg",
                library_index=library_index,
                unmatched_csv_path=str(unmatched_csv),
            )

            assert lost_songs_path.exists()
            content = lost_songs_path.read_text(encoding="utf-8-sig")
            assert "Artist One" in content
            assert "Track One" in content
            assert "https://open.spotify.com/track/url1" in content
            assert "lost_at" in content

    def test_backspace_removes_from_unmatched_csv(self, tmp_path):
        """Pressing backspace removes the song's row from unmatched.csv."""
        unmatched_csv = tmp_path / "unmatched.csv"
        unmatched_csv.write_text(
            "playlist_name,track_id,track_name,artist_names,album_name,tier_tried,spotify_url\n"
            "My Playlist,track123,Track One,Artist One,Album One,tier3,https://open.spotify.com/track/url1\n"
            "Other Playlist,track456,Track Two,Artist Two,Album Two,tier1,https://open.spotify.com/track/url2\n",
            encoding="utf-8-sig",
        )

        batch = ["https://open.spotify.com/track/url1"]
        metadata = {
            "https://open.spotify.com/track/url1": {"artist": "Artist One", "track": "Track One"},
        }
        library_index = {}

        with mock.patch('download.fallback._read_fallback_input', return_value=('lost', None)):
            process_fallback(
                batch=batch,
                metadata=metadata,
                output_dir=str(tmp_path),
                format="mp3",
                overwrite_errors=False,
                cookies_from_browser=None,
                resolved_ffmpeg="/usr/bin/ffmpeg",
                library_index=library_index,
                unmatched_csv_path=str(unmatched_csv),
            )

            content = unmatched_csv.read_text(encoding="utf-8-sig")
            assert "url1" not in content
            assert "url2" in content  # other URL preserved
            assert "Track Two" in content

    def test_backspace_all_songs_batch_not_successful(self):
        """When all songs in a batch are marked lost, batch_succeeded_via_fallback is False."""
        batch = ["url1", "url2"]
        metadata = {
            "url1": {"artist": "Artist 1", "track": "Track 1"},
            "url2": {"artist": "Artist 2", "track": "Track 2"},
        }
        library_index = {}

        with mock.patch('download.fallback._read_fallback_input', return_value=('lost', None)):
            successful, failed, batch_succeeded = process_fallback(
                batch=batch,
                metadata=metadata,
                output_dir="/tmp/output",
                format="mp3",
                overwrite_errors=False,
                cookies_from_browser=None,
                resolved_ffmpeg="/usr/bin/ffmpeg",
                library_index=library_index,
            )

            assert successful == []
            assert failed == []  # lost songs are not failures
            assert batch_succeeded is False

    def test_backspace_no_unmatched_csv_path_no_crash(self):
        """When unmatched_csv_path is None, backspace still marks as lost without writing CSVs."""
        batch = ["url1"]
        metadata = {
            "url1": {"artist": "Artist 1", "track": "Track 1"},
        }
        library_index = {}

        with mock.patch('download.fallback._read_fallback_input', return_value=('lost', None)):
            successful, failed, batch_succeeded = process_fallback(
                batch=batch,
                metadata=metadata,
                output_dir="/tmp/output",
                format="mp3",
                overwrite_errors=False,
                cookies_from_browser=None,
                resolved_ffmpeg="/usr/bin/ffmpeg",
                library_index=library_index,
                # unmatched_csv_path not provided
            )

            assert successful == []
            assert failed == []
            assert batch_succeeded is False
