import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Import the script to be tested. It lives in the bin directory.
sys.path.append('bin')
import cadinstall

class TestCadinstall(unittest.TestCase):

    @patch('cadinstall.os.path.exists')
    @patch('cadinstall.log')
    def test_check_src_exists(self, mock_log, mock_exists):
        mock_exists.return_value = True
        cadinstall.check_src('/tools_vendor/synopsys/vcs/U-2023.03-SP2-5')
        mock_log.error.assert_not_called()

    @patch('cadinstall.os.path.exists')
    @patch('cadinstall.log')
    def test_check_src_not_exists(self, mock_log, mock_exists):
        mock_exists.return_value = False
        with self.assertRaises(SystemExit):
            cadinstall.check_src('/fake/src')
        mock_log.error.assert_called_with('Source directory does not exist: /fake/src')

if __name__ == '__main__':
    unittest.main()