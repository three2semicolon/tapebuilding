"""Tests for tapebuilding.pipelines."""
import unittest

import core


class TestPipelines(unittest.TestCase):
    def test_import(self):
        self.assertIsNotNone(core)
        # Ensure some expected symbols exist
        self.assertTrue(hasattr(core, 'download_songs'))


if __name__ == '__main__':
    unittest.main()