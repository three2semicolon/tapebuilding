"""Tests for the organize.validate module."""

import tempfile
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from organize.validate import validate_file, validate


def test_validate_file_not_found():
    """Test validate_file with non-existent file."""
    result = validate_file('/non/existent/file.mp3', '/some/crate')
    assert result['ok'] is False
    assert 'File not found' in result['error']


def test_validate_file_crate_not_found():
    """Test validate_file with non-existent crate."""
    with tempfile.NamedTemporaryFile() as tmp:
        result = validate_file(tmp.name, '/non/existent/crate')
        assert result['ok'] is False
        assert 'Crate not found' in result['error']


def test_validate_file_valid_inputs():
    """Test validate_file with valid inputs."""
    with tempfile.NamedTemporaryFile() as tmp_file:
        with tempfile.TemporaryDirectory() as tmp_crate:
            result = validate_file(tmp_file.name, tmp_crate)
            assert result['ok'] is True
            assert result['validated'] is True
            assert result['fixes_suggested'] == 0


def test_validate_command_no_args():
    """Test validate command with no arguments."""
    runner = CliRunner()
    # We need to mock resolve_path to simulate ARCHIVE_PATH not being set
    with patch('organize.validate.resolve_path') as mock_resolve_path:
        mock_resolve_path.side_effect = Exception('ARCHIVE_PATH not set - pass it explicitly or add it to .env')
        result = runner.invoke(validate)
        assert result.exit_code != 0
        assert 'error: Could not resolve crate path:' in result.output


def test_validate_command_help():
    """Test validate command help."""
    runner = CliRunner()
    result = runner.invoke(validate, ['--help'])
    assert result.exit_code == 0
    assert 'Unified validation and organization command' in result.output


@patch('organize.validate.resolve_path')
def test_validate_all_flag(mock_resolve_path):
    """Test validate command with --all flag."""
    # Mock resolve_path to return a fake crate path
    mock_resolve_path.return_value = '/fake/crate'

    # Mock the functions that would be called
    with patch('organize.validate.preimport_stage') as mock_preimport, \
         patch('organize.validate.run_import') as mock_import, \
         patch('organize.validate.cleanup_apply.run_cleanup') as mock_cleanup:

        # Set up mock return values
        mock_preimport.return_value = {'staged_folders': 5}
        mock_import.return_value = {'ok': True}
        mock_cleanup.return_value = True

        runner = CliRunner()
        result = runner.invoke(validate, ['--all'])

        assert result.exit_code == 0
        # Check that the success message is in the output
        assert 'Full organize pipeline completed successfully!' in result.output

        # Verify the mocked functions were called
        mock_preimport.assert_called_once()
        mock_import.assert_called_once()
        mock_cleanup.assert_called_once()


@patch('organize.validate.resolve_path')
def test_validate_single_file(mock_resolve_path):
    """Test validate command with a single file."""
    # Mock resolve_path to return a fake crate path
    mock_resolve_path.return_value = '/fake/crate'

    # Mock validate_file to return success
    with patch('organize.validate.validate_file') as mock_validate_file:
        mock_validate_file.return_value = {'ok': True, 'validated': True, 'fixes_suggested': 0}

        runner = CliRunner()
        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile() as tmp_file:
            result = runner.invoke(validate, [tmp_file.name])

            assert result.exit_code == 0
            assert 'File validation completed successfully!' in result.output

            # Verify validate_file was called with correct arguments
            mock_validate_file.assert_called_once_with(tmp_file.name, '/fake/crate')


@patch('organize.validate.resolve_path')
def test_validate_single_file_failure(mock_resolve_path):
    """Test validate command with a single file that fails validation."""
    # Mock resolve_path to return a fake crate path
    mock_resolve_path.return_value = '/fake/crate'

    # Mock validate_file to return failure
    with patch('organize.validate.validate_file') as mock_validate_file:
        mock_validate_file.return_value = {'ok': False, 'error': 'Test error'}

        runner = CliRunner()
        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile() as tmp_file:
            result = runner.invoke(validate, [tmp_file.name])

            assert result.exit_code != 0
            assert 'error: Test error' in result.output

            # Verify validate_file was called with correct arguments
            mock_validate_file.assert_called_once_with(tmp_file.name, '/fake/crate')


@patch('organize.validate.resolve_path')
def test_validate_with_apply_flag(mock_resolve_path):
    """Test validate command with --apply flag."""
    # Mock resolve_path to return a fake crate path
    mock_resolve_path.return_value = '/fake/crate'

    # Mock validate_file to return success
    with patch('organize.validate.validate_file') as mock_validate_file:
        mock_validate_file.return_value = {'ok': True, 'validated': True, 'fixes_suggested': 0}

        runner = CliRunner()
        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile() as tmp_file:
            result = runner.invoke(validate, [tmp_file.name, '--apply'])

            assert result.exit_code == 0
            assert 'File validation completed successfully!' in result.output

            # Verify validate_file was called with correct arguments
            mock_validate_file.assert_called_once_with(tmp_file.name, '/fake/crate')


@patch('organize.validate.resolve_path')
def test_validate_with_verbose_flag(mock_resolve_path):
    """Test validate command with --verbose flag."""
    # Mock resolve_path to return a fake crate path
    mock_resolve_path.return_value = '/fake/crate'

    # Mock validate_file to return success
    with patch('organize.validate.validate_file') as mock_validate_file:
        mock_validate_file.return_value = {'ok': True, 'validated': True, 'fixes_suggested': 0}

        runner = CliRunner()
        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile() as tmp_file:
            result = runner.invoke(validate, [tmp_file.name, '--verbose'])

            assert result.exit_code == 0
            # Verbose flag should increase output but not change success
            assert 'File validation completed successfully!' in result.output

            # Verify validate_file was called with correct arguments
            mock_validate_file.assert_called_once_with(tmp_file.name, '/fake/crate')


if __name__ == '__main__':
    pytest.main([__file__])
