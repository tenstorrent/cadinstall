# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Import the script to be tested. It lives in the bin directory.
sys.path.append('bin')
sys.path.append('lib')
import cadinstall
from utils import check_disk_space_precheck, get_directory_size, get_available_space, format_bytes

## redefine the global variables for cadtools_user and cadtools_group within the unittest since they don't exist outside of linux
cadinstall.cadtools_user = os.getenv('USER', 'unknown_user')
cadinstall.cadtools_group = 'everyone'

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

    @patch('cadinstall.os.path.exists')
    @patch('cadinstall.log')
    def test_check_dest_exists(self, mock_log, mock_exists):
        mock_exists.return_value = True
        with self.assertRaises(SystemExit):
            cadinstall.check_dest('/tools_vendor/synopsys/vcs/U-2023.03-SP2-5')
        mock_log.error.assert_called_with('Destination directory already exists: /tools_vendor/synopsys/vcs/U-2023.03-SP2-5')

    @patch('cadinstall.os.path.exists')
    @patch('cadinstall.log')
    def test_check_dest_not_exists(self, mock_log, mock_exists):
        mock_exists.return_value = False
        cadinstall.check_dest('/fake/dest')
        mock_log.error.assert_not_called()

    @patch('cadinstall.os.makedirs')
    @patch('cadinstall.os.chown')
    @patch('cadinstall.os.chmod')
    @patch('cadinstall.log')
    def test_create_dest(self, mock_log, mock_chmod, mock_chown, mock_makedirs):
        cadinstall.pretend = False
        cadinstall.create_dest('/tools_vendor/synopsys/vcs/U-2023.03-SP2-5')
        mock_makedirs.assert_called_once_with('/tools_vendor/synopsys/vcs/U-2023.03-SP2-5', mode=0o755)
        mock_chown.assert_called_once()
        mock_chmod.assert_called_once_with('/tools_vendor/synopsys/vcs/U-2023.03-SP2-5', 0o755)
        mock_log.info.assert_called_with('Creating destination directory: /tools_vendor/synopsys/vcs/U-2023.03-SP2-5')

    @patch('cadinstall.subprocess.check_call')
    @patch('cadinstall.log')
    def test_run_command(self, mock_log, mock_check_call):
        cadinstall.pretend = False
        cadinstall.run_command('echo test')
        mock_check_call.assert_called_once_with('echo test', shell=True)
        mock_log.info.assert_called_with('Running command: echo test')

    @patch('cadinstall.subprocess.check_call')
    @patch('cadinstall.log')
    def test_run_command_pretend(self, mock_log, mock_check_call):
        cadinstall.pretend = True
        cadinstall.run_command('echo test')
        mock_check_call.assert_not_called()
        mock_log.info.assert_called_with("Because the '-p' switch was thrown, not actually running command: echo test")

    @patch('cadinstall.run_command')
    @patch('cadinstall.create_dest')
    @patch('cadinstall.check_dest')
    @patch('cadinstall.check_src')
    def test_install_tool(self, mock_check_src, mock_check_dest, mock_create_dest, mock_run_command):
        cadinstall.install_tool('synopsys', 'vcs', 'U-2023.03-SP2-5', '/src', 'all', 'cadtools')
        mock_check_src.assert_called_once_with('/src')
        mock_check_dest.assert_called_once_with('/tools_vendor')
        mock_create_dest.assert_called_once_with('/tools_vendor')
        mock_run_command.assert_called_once()

    def test_format_bytes(self):
        """Test byte formatting function"""
        self.assertEqual(format_bytes(1024), "1.00 KB")
        self.assertEqual(format_bytes(1024 * 1024), "1.00 MB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024), "1.00 GB")
        self.assertEqual(format_bytes(500), "500.00 B")

    @patch('utils.get_directory_size')
    @patch('utils.get_available_space')
    @patch('utils.logger')
    def test_disk_space_precheck_success(self, mock_logger, mock_get_available_space, mock_get_directory_size):
        """Test successful disk space precheck"""
        # Mock source size as 1GB (note: in real pretend mode, this would be calculated for real)
        mock_get_directory_size.return_value = 1024 * 1024 * 1024
        # Mock available space as 10GB (more than required 1.2GB)
        mock_get_available_space.return_value = 10 * 1024 * 1024 * 1024
        
        success, sites_with_space, sites_without_space = check_disk_space_precheck(
            '/test/src', ['aus', 'yyz'], 'synopsys', 'vcs', '2023.12', '/tools_vendor')
        
        self.assertTrue(success)
        self.assertEqual(sites_with_space, ['aus', 'yyz'])
        self.assertEqual(sites_without_space, [])

    @patch('utils.get_directory_size')
    @patch('utils.get_available_space')
    @patch('utils.logger')
    def test_disk_space_precheck_partial_failure(self, mock_logger, mock_get_available_space, mock_get_directory_size):
        """Test disk space precheck with some sites failing"""
        # Mock source size as 1GB
        mock_get_directory_size.return_value = 1024 * 1024 * 1024
        # Mock available space - first call returns 10GB (sufficient), second returns 500MB (insufficient)
        mock_get_available_space.side_effect = [10 * 1024 * 1024 * 1024, 500 * 1024 * 1024]
        
        success, sites_with_space, sites_without_space = check_disk_space_precheck(
            '/test/src', ['aus', 'yyz'], 'synopsys', 'vcs', '2023.12', '/tools_vendor')
        
        self.assertFalse(success)
        self.assertEqual(sites_with_space, ['aus'])
        self.assertEqual(sites_without_space, ['yyz'])

    @patch('utils.get_directory_size')
    @patch('utils.get_available_space')
    @patch('utils.logger')
    def test_disk_space_precheck_total_failure(self, mock_logger, mock_get_available_space, mock_get_directory_size):
        """Test disk space precheck with all sites failing"""
        # Mock source size as 1GB
        mock_get_directory_size.return_value = 1024 * 1024 * 1024
        # Mock available space as 500MB (insufficient for both sites)
        mock_get_available_space.return_value = 500 * 1024 * 1024
        
        success, sites_with_space, sites_without_space = check_disk_space_precheck(
            '/test/src', ['aus', 'yyz'], 'synopsys', 'vcs', '2023.12', '/tools_vendor')
        
        self.assertFalse(success)
        self.assertEqual(sites_with_space, [])
        self.assertEqual(sites_without_space, ['aus', 'yyz'])


if __name__ == '__main__':
    unittest.main()
