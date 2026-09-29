# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

import base64
import logging
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.my_globals
from lib.post_exec import (
    POST_EXEC_FILENAME,
    PostExecError,
    _REMOTE_CHECK,
    _assert_trusted_binary,
    _ssh_command,
    contained_target,
    execute_post_exec,
    lexical_release_path,
    load_allowed_commands,
    validate_post_exec,
)

logging.getLogger('cadinstall').addHandler(logging.NullHandler())

EXAMPLE_SCRIPT = """\
sudo /usr/bin/chown sa-rvipeng:sg-ip-release-uploaders ./bin/ip-release-upload-helper
sudo /usr/bin/chmod 4750 ./bin/ip-release-upload-helper 
sudo /usr/bin/chown sa-rvipeng:vendor_tools ./libexec/ip-release-upload-extractor.sif 
sudo /usr/bin/chmod 0444 ./libexec/ip-release-upload-extractor.sif
"""


class Result(object):
    def __init__(self, returncode, stdout='', stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestPostExec(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = self.tmp.name
        self.bin_dir = os.path.join(self.src, 'bin')
        self.libexec = os.path.join(self.src, 'libexec')
        os.makedirs(self.bin_dir)
        os.makedirs(self.libexec)
        self.helper = os.path.join(self.bin_dir, 'ip-release-upload-helper')
        self.sif = os.path.join(self.libexec, 'ip-release-upload-extractor.sif')
        open(self.helper, 'w').close()
        open(self.sif, 'w').close()
        lib.my_globals.set_pretend(False)

    def tearDown(self):
        lib.my_globals.set_pretend(False)
        self.tmp.cleanup()

    def _write(self, text):
        path = os.path.join(self.src, POST_EXEC_FILENAME)
        with open(path, 'w') as handle:
            handle.write(text)
        return path

    def _validate(self, text):
        self._write(text)
        return validate_post_exec(self.src)

    def test_allowlist_is_only_the_three_commands(self):
        self.assertEqual(
            load_allowed_commands(),
            set([
                'sudo /usr/bin/chown',
                'sudo /usr/bin/chmod',
                'sudo /usr/bin/chgrp',
            ]),
        )

    def test_allowlist_rejects_unknown_command(self):
        path = os.path.join(self.src, 'allowed')
        with open(path, 'w') as handle:
            handle.write('sudo /bin/rm\n')
        self._write(EXAMPLE_SCRIPT)
        with self.assertRaises(PostExecError) as caught:
            validate_post_exec(self.src, allowed_commands_file=path)
        self.assertIn('unsupported command', str(caught.exception))

    def test_missing_script_is_skipped(self):
        plan = validate_post_exec(self.src)
        self.assertFalse(plan)
        self.assertEqual(len(plan), 0)

    def test_example_script_passes_precheck(self):
        plan = self._validate(EXAMPLE_SCRIPT)
        self.assertEqual(len(plan), 4)
        self.assertEqual(plan.commands[0].kind, 'chown')
        self.assertEqual(plan.commands[0].operand, 'sa-rvipeng:sg-ip-release-uploaders')
        self.assertEqual(plan.commands[0].relpath, './bin/ip-release-upload-helper')
        self.assertEqual(plan.commands[1].kind, 'chmod')
        self.assertEqual(plan.commands[1].operand, '4750')
        self.assertEqual(plan.commands[3].operand, '0444')

    def test_chown_accepts_a_username_without_a_group(self):
        text = """\
sudo /usr/bin/chown sa-rvipeng ./bin/ip-release-upload-helper
sudo /usr/bin/chmod 4750 ./bin/ip-release-upload-helper 
sudo /usr/bin/chown sa-rvipeng:vendor_tools ./libexec/ip-release-upload-extractor.sif 
sudo /usr/bin/chmod 0444 ./libexec/ip-release-upload-extractor.sif
"""
        plan = self._validate(text)
        self.assertEqual(plan.commands[0].operand, 'sa-rvipeng')
        self.assertEqual(plan.commands[2].operand, 'sa-rvipeng:vendor_tools')

    def test_recursive_chown_of_the_release_root(self):
        plan = self._validate("sudo /usr/bin/chown -R sa-rvipeng ./\n")
        self.assertTrue(plan.commands[0].recursive)
        self.assertEqual(plan.commands[0].relpath, './')
        self.assertEqual(plan.commands[0].operand, 'sa-rvipeng')

    def test_glob_stays_inside_and_dotdot_glob_is_rejected(self):
        plan = self._validate("sudo /usr/bin/chown -R sa-rvipeng ./*\n")
        self.assertEqual(plan.commands[0].relpath, './*')
        for line in (
            "sudo /usr/bin/chown -R sa-rvipeng ./../*\n",
            "sudo /usr/bin/chown -R sa-rvipeng ./../bin\n",
            "sudo /usr/bin/chown -R sa-rvipeng ./* /etc\n",
            "sudo /usr/bin/chown -R sa-rvipeng *\n",
            "sudo /usr/bin/chmod -R 755 ./bin/../../etc/*\n",
        ):
            with self.assertRaises(PostExecError, msg=line):
                self._validate(line)

    def test_comments_blank_lines_and_shebang_are_ignored(self):
        text = "\n# comment\n#!/bin/sh\n\n" + EXAMPLE_SCRIPT + "\n"
        plan = self._validate(text)
        self.assertEqual(len(plan), 4)

    def test_chgrp_and_directory_target(self):
        plan = self._validate("sudo /usr/bin/chgrp vendor_tools ./bin\n")
        self.assertEqual(plan.commands[0].kind, 'chgrp')
        self.assertEqual(plan.commands[0].relpath, './bin')
        self.assertTrue(os.path.isdir(contained_target(self.src, './bin')))

    def test_disabled_command_is_rejected(self):
        path = os.path.join(self.src, 'allowed')
        with open(path, 'w') as handle:
            handle.write('sudo /usr/bin/chmod\n')
        self._write("sudo /usr/bin/chown sa-rvipeng:vendor_tools ./bin/ip-release-upload-helper\n")
        with self.assertRaises(PostExecError) as caught:
            validate_post_exec(self.src, allowed_commands_file=path)
        self.assertIn('not allowed', str(caught.exception))

    def test_rejects_shell_metacharacters(self):
        attacks = [
            "sudo /usr/bin/chmod 4750 ./bin/ip-release-upload-helper; /bin/rm -rf /",
            "sudo /usr/bin/chmod 4750 ./bin/ip-release-upload-helper && /bin/rm -rf /",
            "sudo /usr/bin/chmod 4750 ./bin/ip-release-upload-helper | /bin/sh",
            "sudo /usr/bin/chmod 4750 `whoami`",
            "sudo /usr/bin/chmod 4750 $(whoami)",
            "sudo /usr/bin/chmod 4750 ./bin/ip-release-upload-helper > /etc/passwd",
            "sudo /usr/bin/chown sa-rvipeng:vendor_tools ./bin/ip-release-upload-helper\n/bin/rm -rf /",
        ]
        for attack in attacks:
            with self.assertRaises(PostExecError):
                self._validate(attack)

    def test_rejects_flags_absolute_paths_and_dotdot(self):
        rejected = [
            "sudo /usr/bin/chown --from=root sa-rvipeng:vendor_tools ./bin/ip-release-upload-helper",
            "sudo /usr/bin/chown -L sa-rvipeng ./",
            "sudo /usr/bin/chown -RL sa-rvipeng ./",
            "sudo /usr/bin/chown -R -H sa-rvipeng ./",
            "sudo /usr/bin/chmod 4750 /etc/passwd",
            "sudo /usr/bin/chmod 4750 ./bin/../../etc/passwd",
            "sudo /usr/bin/chmod 4750 ./bin/../libexec/ip-release-upload-extractor.sif",
            "sudo /bin/chmod 4750 ./bin/ip-release-upload-helper",
            "sudo /usr/bin/rm -rf ./bin/ip-release-upload-helper",
            "/usr/bin/chmod 4750 ./bin/ip-release-upload-helper",
            "sudo /usr/bin/chmod a+x ./bin/ip-release-upload-helper",
            "sudo /usr/bin/chmod 8 ./bin/ip-release-upload-helper",
            "sudo /usr/bin/chmod 04750 ./bin/ip-release-upload-helper",
            "sudo /usr/bin/chown 0:0 ./bin/ip-release-upload-helper",
            "sudo /usr/bin/chown 0 ./bin/ip-release-upload-helper",
            "sudo /usr/bin/chown :vendor_tools ./bin/ip-release-upload-helper",
            "sudo /usr/bin/chown sa-rvipeng: ./bin/ip-release-upload-helper",
            "sudo /usr/bin/chgrp 0 ./bin",
            "sudo /usr/bin/chmod 4750 ./bin/ip-release-upload-helper ./libexec/ip-release-upload-extractor.sif",
            "sudo /usr/bin/chmod 4750 ./.cadinstall.post-exec.sh",
            "sudo /usr/bin/chmod  4750 ./bin/ip-release-upload-helper",
        ]
        for line in rejected:
            with self.assertRaises(PostExecError, msg=line):
                self._validate(line + "\n")

    def test_rejects_missing_symlink_hardlink_and_special_files(self):
        with self.assertRaises(PostExecError):
            self._validate("sudo /usr/bin/chmod 644 ./bin/does-not-exist\n")

        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: os.rmdir(outside) if os.path.isdir(outside) else None)
        secret = os.path.join(outside, 'secret')
        open(secret, 'w').close()
        self.addCleanup(lambda: os.remove(secret) if os.path.exists(secret) else None)

        os.remove(self.helper)
        os.symlink(secret, self.helper)
        with self.assertRaises(PostExecError) as caught:
            self._validate("sudo /usr/bin/chmod 4750 ./bin/ip-release-upload-helper\n")
        self.assertIn('symlink', str(caught.exception))
        os.remove(self.helper)
        open(self.helper, 'w').close()

        linked = os.path.join(self.src, 'linked')
        os.symlink(outside, linked)
        with self.assertRaises(PostExecError) as caught:
            self._validate("sudo /usr/bin/chmod 644 ./linked/secret\n")
        self.assertIn('symlink', str(caught.exception))

        inside_link = os.path.join(self.bin_dir, 'also-helper')
        os.link(self.helper, inside_link)
        with self.assertRaises(PostExecError) as caught:
            self._validate("sudo /usr/bin/chmod 4750 ./bin/ip-release-upload-helper\n")
        self.assertIn('hard-linked', str(caught.exception))
        os.remove(inside_link)

        fifo = os.path.join(self.bin_dir, 'fifo')
        os.mkfifo(fifo)
        with self.assertRaises(PostExecError) as caught:
            self._validate("sudo /usr/bin/chmod 644 ./bin/fifo\n")
        self.assertIn('non-regular', str(caught.exception))

    def test_rejects_symlink_and_world_writable_script(self):
        real = os.path.join(self.src, 'real-post.sh')
        with open(real, 'w') as handle:
            handle.write(EXAMPLE_SCRIPT)
        script = os.path.join(self.src, POST_EXEC_FILENAME)
        os.symlink(real, script)
        with self.assertRaises(PostExecError) as caught:
            validate_post_exec(self.src)
        self.assertIn('symlink', str(caught.exception))
        os.remove(script)

        self._write(EXAMPLE_SCRIPT)
        os.chmod(script, 0o666)
        with self.assertRaises(PostExecError) as caught:
            validate_post_exec(self.src)
        self.assertIn('world-writable', str(caught.exception))

    def test_rejects_non_ascii_and_nul(self):
        path = os.path.join(self.src, POST_EXEC_FILENAME)
        with open(path, 'wb') as handle:
            handle.write(b'sudo /usr/bin/chmod 755 ./bin/ip-release-upload-helper\xc2\x80\n')
        with self.assertRaises(PostExecError):
            validate_post_exec(self.src)
        with open(path, 'wb') as handle:
            handle.write(b'sudo /usr/bin/chmod 755 ./bin/ip-release-upload-helper\0\n')
        with self.assertRaises(PostExecError):
            validate_post_exec(self.src)

    def test_lexical_path_cannot_escape(self):
        root = '/tools_vendor/acme/tool/1.0'
        self.assertEqual(
            lexical_release_path(root, './bin/ip-release-upload-helper'),
            '/tools_vendor/acme/tool/1.0/bin/ip-release-upload-helper',
        )
        self.assertEqual(lexical_release_path(root, './'), root)
        with self.assertRaises(PostExecError):
            lexical_release_path('/tools_vendor/../../etc', './bin/ip-release-upload-helper')
        with self.assertRaises(PostExecError):
            lexical_release_path(root, './bin/../../etc/passwd')
        with self.assertRaises(PostExecError):
            lexical_release_path('/', './bin/ip-release-upload-helper')

    def test_local_execute_uses_sudo_without_a_shell(self):
        plan = self._validate(EXAMPLE_SCRIPT)
        with patch('lib.post_exec.check_same_host', return_value=0), \
             patch('lib.post_exec._assert_trusted_binary'), \
             patch('lib.post_exec.subprocess.run', return_value=Result(0)) as mock_run:
            execute_post_exec(plan, self.src, 'publish.example.com')

        self.assertEqual(mock_run.call_count, 4)
        commands = [call[0][0] for call in mock_run.call_args_list]
        self.assertEqual(commands[0][0:4], ['/usr/bin/sudo', '-n', '/usr/bin/chown', '-h'])
        self.assertEqual(commands[1][0:3], ['/usr/bin/sudo', '-n', '/usr/bin/chmod'])
        self.assertNotIn('-h', commands[1])
        root = os.path.realpath(self.src)
        for argv in commands:
            target = argv[-1]
            self.assertTrue(target.startswith(root + os.sep), target)
            self.assertNotIn('..', target.split('/'))
            self.assertFalse(mock_run.call_args[1]['shell'])
        self.assertEqual(mock_run.call_args[1]['env'], {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})

    def test_recursive_root_chown_targets_only_the_release(self):
        plan = self._validate("sudo /usr/bin/chown -R sa-rvipeng ./\n")
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: os.rmdir(outside) if os.path.isdir(outside) else None)
        secret = os.path.join(outside, 'secret')
        open(secret, 'w').close()
        self.addCleanup(lambda: os.remove(secret) if os.path.exists(secret) else None)
        os.symlink(secret, os.path.join(self.src, 'escape'))
        with patch('lib.post_exec.check_same_host', return_value=0), \
             patch('lib.post_exec._assert_trusted_binary'), \
             patch('lib.post_exec.subprocess.run', return_value=Result(0)) as mock_run:
            execute_post_exec(plan, self.src, 'publish.example.com')
        argv = mock_run.call_args[0][0]
        self.assertEqual(
            argv,
            ['/usr/bin/sudo', '-n', '/usr/bin/chown', '-R', '-h', 'sa-rvipeng', os.path.realpath(self.src)],
        )
        self.assertFalse(mock_run.call_args[1]['shell'])
        self.assertNotIn(secret, argv)

    def test_glob_expands_inside_the_release_without_a_shell(self):
        plan = self._validate("sudo /usr/bin/chown sa-rvipeng ./*\n")
        with patch('lib.post_exec.check_same_host', return_value=0), \
             patch('lib.post_exec._assert_trusted_binary'), \
             patch('lib.post_exec.subprocess.run', return_value=Result(0)) as mock_run:
            execute_post_exec(plan, self.src, 'publish.example.com')
        argv = mock_run.call_args[0][0]
        root = os.path.realpath(self.src)
        targets = argv[argv.index('sa-rvipeng') + 1:]
        self.assertEqual(targets, [os.path.join(root, 'bin'), os.path.join(root, 'libexec')])
        self.assertNotIn('*', argv)
        self.assertFalse(mock_run.call_args[1]['shell'])

    def test_local_execute_stops_on_first_failure(self):
        plan = self._validate(EXAMPLE_SCRIPT)
        with patch('lib.post_exec.check_same_host', return_value=0), \
             patch('lib.post_exec._assert_trusted_binary'), \
             patch('lib.post_exec.subprocess.run', return_value=Result(1, stderr='denied')) as mock_run:
            with self.assertRaises(PostExecError):
                execute_post_exec(plan, self.src, 'publish.example.com')
        self.assertEqual(mock_run.call_count, 1)

    def test_execute_refuses_a_script_changed_after_precheck(self):
        plan = self._validate(EXAMPLE_SCRIPT)
        with open(plan.script_path, 'a') as handle:
            handle.write("sudo /usr/bin/chmod 777 ./bin/ip-release-upload-helper\n")
        with patch('lib.post_exec.subprocess.run') as mock_run:
            with self.assertRaises(PostExecError) as caught:
                execute_post_exec(plan, self.src, 'publish.example.com')
        self.assertIn('changed', str(caught.exception))
        mock_run.assert_not_called()

    def test_execute_rechecks_a_tampered_plan(self):
        plan = self._validate("sudo /usr/bin/chmod 4750 ./bin/ip-release-upload-helper\n")
        plan.commands[0].relpath = './bin/../../etc/passwd'
        with patch('lib.post_exec.check_same_host', return_value=0), \
             patch('lib.post_exec.subprocess.run') as mock_run:
            with self.assertRaises(PostExecError):
                execute_post_exec(plan, self.src, 'publish.example.com')
        mock_run.assert_not_called()

    def test_pretend_does_not_execute(self):
        plan = self._validate(EXAMPLE_SCRIPT)
        lib.my_globals.set_pretend(True)
        with patch('lib.post_exec.subprocess.run') as mock_run:
            execute_post_exec(plan, self.src, 'publish.example.com')
        mock_run.assert_not_called()

    def test_remote_execute_quotes_the_command_and_checks_the_path_first(self):
        plan = self._validate("sudo /usr/bin/chown sa-rvipeng:vendor_tools ./bin/ip-release-upload-helper\n")
        with patch('lib.post_exec.check_same_host', return_value=1), \
             patch('lib.post_exec.run_command_with_output', return_value=(0, './bin/ip-release-upload-helper\n')) as mock_check, \
             patch('lib.post_exec.run_command', return_value=0) as mock_run:
            execute_post_exec(plan, '/tools_vendor/acme/helper/1.0', 'yyz2-nfspublish.yyz2.tenstorrent.com')

        check = shlex.split(mock_check.call_args[0][0])
        self.assertEqual(check[0], '/usr/bin/ssh')
        self.assertEqual(check[1], 'yyz2-nfspublish.yyz2.tenstorrent.com')
        remote_check = shlex.split(check[2])
        self.assertEqual(remote_check[0], '/usr/bin/python3')
        self.assertEqual(remote_check[1], '-c')
        self.assertNotIn('\n', remote_check[2])
        self.assertEqual(
            base64.b64decode(remote_check[3]).decode('ascii'),
            _REMOTE_CHECK,
        )
        self.assertEqual(remote_check[4], '/tools_vendor/acme/helper/1.0')
        self.assertEqual(remote_check[5], './bin/ip-release-upload-helper')
        self.assertEqual(remote_check[6], 'chown')
        self.assertEqual(remote_check[7], '0')

        sudo = shlex.split(mock_run.call_args[0][0])
        remote_sudo = shlex.split(sudo[2])
        self.assertEqual(
            remote_sudo,
            [
                '/usr/bin/sudo', '-n', '/usr/bin/chown', '-h',
                'sa-rvipeng:vendor_tools',
                '/tools_vendor/acme/helper/1.0/bin/ip-release-upload-helper',
            ],
        )
        self.assertNotIn(';', mock_run.call_args[0][0])
        self.assertNotIn('|', mock_run.call_args[0][0])

    def test_remote_sudo_is_not_run_when_the_path_check_fails(self):
        plan = self._validate("sudo /usr/bin/chmod 4750 ./bin/ip-release-upload-helper\n")
        with patch('lib.post_exec.check_same_host', return_value=1), \
             patch('lib.post_exec.run_command_with_output', return_value=(5, '')), \
             patch('lib.post_exec.run_command') as mock_run:
            with self.assertRaises(PostExecError) as caught:
                execute_post_exec(plan, '/tools_vendor/acme/helper/1.0', 'publish.example.com')
        self.assertIn('escapes', str(caught.exception))
        mock_run.assert_not_called()

    def test_ssh_command_refuses_an_unsafe_host(self):
        with self.assertRaises(PostExecError):
            _ssh_command('host;rm', ['/usr/bin/true'])

    def test_remote_check_script_agrees_with_local_rules(self):
        good = subprocess.run(
            ['/usr/bin/python3', '-c', _REMOTE_CHECK, self.src, './bin/ip-release-upload-helper'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        self.assertEqual(good.returncode, 0, good.stderr)

        os.remove(self.helper)
        secret = os.path.join(self.tmp.name, 'secret')
        open(secret, 'w').close()
        os.symlink(secret, self.helper)
        owned = subprocess.run(
            ['/usr/bin/python3', '-c', _REMOTE_CHECK, self.src, './bin/ip-release-upload-helper', 'chown', '0'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        self.assertEqual(owned.returncode, 0, owned.stderr)
        self.assertNotIn(secret, owned.stdout)
        self.assertIn('./bin/ip-release-upload-helper', owned.stdout)
        bad = subprocess.run(
            ['/usr/bin/python3', '-c', _REMOTE_CHECK, self.src, './bin/ip-release-upload-helper', 'chmod', '0'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        self.assertEqual(bad.returncode, 3)
        self.assertIn('symlink', bad.stderr)
        escaped = subprocess.run(
            ['/usr/bin/python3', '-c', _REMOTE_CHECK, self.src, './../*', 'chown', '1'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        self.assertNotEqual(escaped.returncode, 0)

    def test_trusted_binary_rejects_a_file_in_the_tree(self):
        with self.assertRaises(PostExecError):
            _assert_trusted_binary(self.helper)
        with self.assertRaises(PostExecError):
            _assert_trusted_binary('/bin/sh')

    def test_missing_source_directory_fails_closed(self):
        with self.assertRaises(PostExecError):
            validate_post_exec(os.path.join(self.src, 'missing'))


if __name__ == '__main__':
    unittest.main()
