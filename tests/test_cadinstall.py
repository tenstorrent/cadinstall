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

    def test_dest_permissions_are_not_group_writable(self):
        """Installed trees must be 2755 / cadtools, not umask 775 group-write."""
        from tool_defs import dest_mode, dest_group, rsync_chmod, rsync_options

        self.assertEqual(dest_mode, 0o2755)
        self.assertEqual(format(dest_mode, 'o'), '2755')
        self.assertEqual(dest_group, 'cadtools')
        self.assertIn('a=rX', rsync_chmod)
        self.assertIn('Dg+s', rsync_chmod)
        self.assertNotIn('g+rx', rsync_options)
        self.assertIn('--chmod=a=rX,u+w,Dg+s', rsync_options)

    def _rsync_command_from_install(self, same_host, group='cadtools'):
        """Run install_tool with mocks and return the rsync command string."""
        from lib.install import install_tool

        with patch('lib.install.check_src'), \
             patch('lib.install.ensure_dest_directory'), \
             patch('lib.install.apply_install_permissions'), \
             patch('lib.install.check_same_host', return_value=0 if same_host else 1), \
             patch('lib.install.run_command', return_value=0) as mock_run:
            install_tool(
                'synopsys', 'test', 'test6', '/src', group,
                'yyz2-nfspublish.yyz2.tenstorrent.com',
                '/tools_vendor/synopsys/test/test6')
            return mock_run.call_args[0][0]

    def test_install_rsync_uses_chown_without_groupmap(self):
        """--chown and --groupmap cannot be combined (rsync 3.1.3)."""
        for same_host in (True, False):
            command = self._rsync_command_from_install(same_host)
            self.assertIn('--chown=cadtools:cadtools', command)
            self.assertNotIn('--groupmap', command)

    def test_shell_owner_group_quotes_spaces(self):
        """--group values with spaces (e.g. domain users) must be quoted."""
        from lib.install import shell_owner_group

        self.assertEqual(shell_owner_group('cadtools', 'cadtools'), 'cadtools:cadtools')
        self.assertEqual(
            shell_owner_group('cadtools', 'domain users'),
            "'cadtools:domain users'")

    def test_install_rsync_quotes_group_with_spaces(self):
        """--group replaces dest_group and is quoted for the shell."""
        for same_host in (True, False):
            command = self._rsync_command_from_install(same_host, group='domain users')
            self.assertIn("--chown='cadtools:domain users'", command)
            self.assertNotIn('--chown=cadtools:domain users', command)

    def test_apply_install_permissions_quotes_group_with_spaces(self):
        """Post-rsync chown must quote groups that contain spaces."""
        from lib.install import apply_install_permissions

        with patch('lib.install.check_same_host', return_value=0), \
             patch('lib.install.run_command', return_value=0) as mock_run:
            apply_install_permissions('/dest', 'localhost', 'domain users')
            commands = [call[0][0] for call in mock_run.call_args_list]
            chown_cmds = [cmd for cmd in commands if '/usr/bin/chown' in cmd]
            self.assertEqual(len(chown_cmds), 1)
            self.assertIn("/usr/bin/chown -R 'cadtools:domain users' /dest", chown_cmds[0])

        with patch('lib.install.check_same_host', return_value=1), \
             patch('lib.install.run_command', return_value=0) as mock_run:
            apply_install_permissions('/dest', 'remote.host', 'domain users')
            commands = [call[0][0] for call in mock_run.call_args_list]
            chown_cmds = [cmd for cmd in commands if 'chown' in cmd]
            self.assertEqual(len(chown_cmds), 1)
            # Entire remote command is quoted so the group survives ssh.
            self.assertIn('chown', chown_cmds[0])
            self.assertIn('domain users', chown_cmds[0])
            self.assertIn("'", chown_cmds[0])


if __name__ == '__main__':
    unittest.main()
