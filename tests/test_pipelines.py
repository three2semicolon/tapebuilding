"""Tests for tapebuilding.pipelines."""
import unittest

import pipelines


class TestPipelines(unittest.TestCase):
    def test_import(self):
        self.assertIsNotNone(pipelines)
        # Ensure some expected symbols exist
        self.assertTrue(hasattr(pipelines, 'download_songs'))


if __name__ == '__main__':
    unittest.main()