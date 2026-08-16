"""Tests for tapebuilding.downloader."""

import unittest

class TestDownloader(unittest.TestCase):
    def test_import(self):
        from tapebuilding import downloader
        self.assertIsNotNone(downloader)
        self.assertTrue(hasattr(downloader, 'download'))

    def test_download_callable(self):
        from tapebuilding import downloader
        self.assertTrue(callable(downloader.download))

if __name__ == '__main__':
    unittest.main()