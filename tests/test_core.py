"""Tests for tapebuilding.core."""

import unittest

class TestCore(unittest.TestCase):
    def test_import(self):
        from tapebuilding import core
        self.assertIsNotNone(core)

    def test_defaults_exist(self):
        from tapebuilding import core
        self.assertTrue(hasattr(core, 'DEFAULT_FORMAT'))
        self.assertTrue(hasattr(core, 'DEFAULT_BITRATE'))
        self.assertTrue(hasattr(core, 'VERBOSE'))

if __name__ == '__main__':
    unittest.main()