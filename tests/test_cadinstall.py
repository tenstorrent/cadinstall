import unittest
from unittest.mock import patch, call, MagicMock
import os
import subprocess
import unittest
from unittest.mock import patch, call, MagicMock
import os
import subprocess
import sys

# Assuming cadinstall.py is in the parallel bin directory to this test file
sys.path.append('/Users/bswan/Applications/cadinstall')
import bin.cadinstall as cadinstall

class TestCadInstall(unittest.TestCase):

    @patch('bin.cadinstall.subprocess.check_call')
    @patch('bin.cadinstall.log')
    def test_run_command(self, mock_log, mock_check_call):
        # Test when pretend is True
        cadinstall.pretend = True
        cadinstall.run_command('echo test')
        mock_log.info.assert_called_with("Because the '-p' switch was thrown, not actually running command: echo test")
        mock_check_call.assert_not_called()

        # Test when pretend is False
        cadinstall.pretend = False
        cadinstall.run_command('echo test')
        mock_log.info.assert_called_with("Running command: echo test")
        mock_check_call.assert_called_with('echo test', shell=True)

        # Test command failure
        mock_check_call.side_effect = subprocess.CalledProcessError(1, 'echo test')
        with self.assertRaises(SystemExit):
            cadinstall.run_command('echo test')
        mock_log.error.assert_called_with("Error running command: echo test")

    @patch('bin.cadinstall.os.path.exists')
    @patch('bin.cadinstall.log')
    def test_check_src(self, mock_log, mock_exists):
        # Test when src exists
        mock_exists.return_value = True
        cadinstall.check_src('/path/to/src')
        mock_log.error.assert_not_called()

        # Test when src does not exist
        mock_exists.return_value = False
        with self.assertRaises(SystemExit):
            cadinstall.check_src('/path/to/src')
        mock_log.error.assert_called_with("Source directory does not exist: /path/to/src")

    @patch('bin.cadinstall.os.path.exists')
    @patch('bin.cadinstall.log')
    def test_check_dest(self, mock_log, mock_exists):
        # Test when dest does not exist
        mock_exists.return_value = False
        cadinstall.check_dest('/path/to/dest')
        mock_log.error.assert_not_called()

        # Test when dest exists
        mock_exists.return_value = True
        with self.assertRaises(SystemExit):
            cadinstall.check_dest('/path/to/dest')
        mock_log.error.assert_called_with("Destination directory already exists: /path/to/dest")

    @patch('bin.cadinstall.os.makedirs')
    @patch('bin.cadinstall.os.chown')
    @patch('bin.cadinstall.os.chmod')
    @patch('bin.cadinstall.pwd.getpwnam')
    @patch('bin.cadinstall.grp.getgrnam')
    @patch('bin.cadinstall.log')
    def test_create_dest(self, mock_log, mock_getgrnam, mock_getpwnam, mock_chmod, mock_chown, mock_makedirs):
        # Test when pretend is True
        cadinstall.pretend = True
        cadinstall.create_dest('/path/to/dest')
        mock_log.info.assert_called_with("Creating destination directory: /path/to/dest")
        mock_makedirs.assert_not_called()
        mock_chown.assert_not_called()
        mock_chmod.assert_not_called()

        # Test when pretend is False
        cadinstall.pretend = False
        cadinstall.create_dest('/path/to/dest')
        mock_log.info.assert_called_with("Creating destination directory: /path/to/dest")
        mock_makedirs.assert_called_with('/path/to/dest', mode=cadinstall.dest_mode)
        mock_chown.assert_called()
        mock_chmod.assert_called_with('/path/to/dest', cadinstall.dest_mode)

    @patch('bin.cadinstall.run_command')
    @patch('bin.cadinstall.check_src')
    @patch('bin.cadinstall.check_dest')
    @patch('bin.cadinstall.create_dest')
    def test_install_tool(self, mock_create_dest, mock_check_dest, mock_check_src, mock_run_command):
        cadinstall.install_tool('vendor', 'tool', 'version', '/path/to/src', 'all', 'cadtools')
        mock_check_src.assert_called_with('/path/to/src')
        mock_check_dest.assert_called_with(cadinstall.dest)
        mock_create_dest.assert_called_with(cadinstall.dest)
        mock_run_command.assert_called_with('/usr/bin/rsync -av /path/to/src /tools_vendor vendor tool version cadtools')

    @patch('bin.cadinstall.run_command')
    @patch('bin.cadinstall.log')
    @patch('bin.cadinstall.sys.exit')
    def test_main_not_cadtools_user(self, mock_exit, mock_log, mock_run_command):
        cadinstall.user = 'not_cadtools'
        cadinstall.main()
        mock_log.info.assert_called_with("Submitting job to jenkins ...")
        mock_run_command.assert_called()
        mock_exit.assert_called_with(0)

    @patch('bin.cadinstall.install_tool')
    @patch('bin.cadinstall.log')
    @patch('bin.cadinstall.sys.exit')
    def test_main_install_subcommand(self, mock_exit, mock_log, mock_install_tool):
        cadinstall.user = 'cadtools'
        cadinstall.args.subcommand = 'install'
        cadinstall.main()
        mock_install_tool.assert_called_with(cadinstall.vendor, cadinstall.tool, cadinstall.version, cadinstall.src, cadinstall.sites, cadinstall.group)
        mock_exit.assert_not_called()

    @patch('bin.cadinstall.parser.print_help')
    @patch('bin.cadinstall.sys.exit')
    def test_main_no_subcommand(self, mock_exit, mock_print_help):
        cadinstall.args.subcommand = None
        cadinstall.main()
        mock_print_help.assert_called()
        mock_exit.assert_called_with(1)

    @patch('bin.cadinstall.parser.print_help')
    @patch('bin.cadinstall.sys.exit')
    def test_main_invalid_subcommand(self, mock_exit, mock_print_help):
        cadinstall.args.subcommand = 'invalid'
        cadinstall.main()
        mock_print_help.assert_called()
        mock_exit.assert_called_with(1)

if __name__ == '__main__':
    unittest.main()
        mock_check_call.assert_called_with('echo test', shell=True)

        # Test command failure
        mock_check_call.side_effect = subprocess.CalledProcessError(1, 'echo test')
        with self.assertRaises(SystemExit):
            cadinstall.run_command('echo test')
        mock_log.error.assert_called_with("Error running command: echo test")

    @patch('cadinstall.os.path.exists')
    @patch('cadinstall.log')
    def test_check_src(self, mock_log, mock_exists):
        # Test when src exists
        mock_exists.return_value = True
        cadinstall.check_src('/path/to/src')
        mock_log.error.assert_not_called()

        # Test when src does not exist
        mock_exists.return_value = False
        with self.assertRaises(SystemExit):
            cadinstall.check_src('/path/to/src')
        mock_log.error.assert_called_with("Source directory does not exist: /path/to/src")

    @patch('cadinstall.os.path.exists')
    @patch('cadinstall.log')
    def test_check_dest(self, mock_log, mock_exists):
        # Test when dest does not exist
        mock_exists.return_value = False
        cadinstall.check_dest('/path/to/dest')
        mock_log.error.assert_not_called()

        # Test when dest exists
        mock_exists.return_value = True
        with self.assertRaises(SystemExit):
            cadinstall.check_dest('/path/to/dest')
        mock_log.error.assert_called_with("Destination directory already exists: /path/to/dest")

    @patch('cadinstall.os.makedirs')
    @patch('cadinstall.os.chown')
    @patch('cadinstall.os.chmod')
    @patch('cadinstall.pwd.getpwnam')
    @patch('cadinstall.grp.getgrnam')
    @patch('cadinstall.log')
    def test_create_dest(self, mock_log, mock_getgrnam, mock_getpwnam, mock_chmod, mock_chown, mock_makedirs):
        # Test when pretend is True
        cadinstall.pretend = True
        cadinstall.create_dest('/path/to/dest')
        mock_log.info.assert_called_with("Creating destination directory: /path/to/dest")
        mock_makedirs.assert_not_called()
        mock_chown.assert_not_called()
        mock_chmod.assert_not_called()

        # Test when pretend is False
        cadinstall.pretend = False
        cadinstall.create_dest('/path/to/dest')
        mock_log.info.assert_called_with("Creating destination directory: /path/to/dest")
        mock_makedirs.assert_called_with('/path/to/dest', mode=cadinstall.dest_mode)
        mock_chown.assert_called()
        mock_chmod.assert_called_with('/path/to/dest', cadinstall.dest_mode)

if __name__ == '__main__':
    unittest.main()