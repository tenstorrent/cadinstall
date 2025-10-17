# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
import sys
import json
import socket

# Add the lib directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import the module to test
from lib import executor

class TestExecutor(unittest.TestCase):
    """Test cases for the executor module"""
    
    def setUp(self):
        """Reset executor state before each test"""
        executor._execution_mode = None
        executor._listener_config = None
        executor._sudo_path = None
    
    @patch('lib.executor.subprocess.run')
    @patch('lib.executor.pwd.getpwuid')
    @patch('lib.executor.os.path.exists')
    @patch('lib.executor.os.stat')
    @patch('lib.executor.logger')
    def test_initialize_executor_setuid_mode(self, mock_logger, mock_stat, mock_exists, mock_getpwuid, mock_subprocess_run):
        """Test initialization with valid setuid binary"""
        # Mock setuid binary exists with setuid bit set
        mock_exists.return_value = True
        mock_stat_result = MagicMock()
        mock_stat_result.st_mode = 0o104755  # setuid bit (04000) + 0755
        mock_stat_result.st_uid = 1000
        mock_stat.return_value = mock_stat_result
        
        # Mock pwd.getpwuid to return expected user
        mock_user = MagicMock()
        mock_user.pw_name = 'cadtools'
        mock_getpwuid.return_value = mock_user
        
        # Mock subprocess.run to simulate successful setuid execution
        mock_run_result = MagicMock()
        mock_run_result.returncode = 0
        mock_run_result.stdout = 'cadtools\n'
        mock_subprocess_run.return_value = mock_run_result
        
        result = executor.initialize_executor()
        
        self.assertTrue(result)
        self.assertEqual(executor.get_execution_mode(), 'setuid')
        self.assertIsNotNone(executor.get_sudo_path())
    
    @patch('lib.executor.subprocess.run')
    @patch('lib.executor.pwd.getpwuid')
    @patch('lib.executor.os.path.exists')
    @patch('lib.executor.os.stat')
    @patch('lib.executor.logger')
    @patch('lib.executor.socket.socket')
    def test_initialize_executor_setuid_not_functional(self, mock_socket_class, mock_logger, mock_stat, mock_exists, mock_getpwuid, mock_subprocess_run):
        """Test initialization when setuid bit is set but not functional (nosuid mount)"""
        # Mock setuid binary exists with setuid bit set
        def exists_side_effect(path):
            if 'sudo' in path:
                return True
            elif 'cadinstall.json' in path:
                return True
            return False
        
        mock_exists.side_effect = exists_side_effect
        
        mock_stat_result = MagicMock()
        mock_stat_result.st_mode = 0o104755  # setuid bit (04000) + 0755
        mock_stat_result.st_uid = 1000
        mock_stat.return_value = mock_stat_result
        
        # Mock pwd.getpwuid to return expected user
        mock_user = MagicMock()
        mock_user.pw_name = 'cadtools'
        mock_getpwuid.return_value = mock_user
        
        # Mock subprocess.run to simulate setuid NOT working (returns current user instead)
        mock_run_result = MagicMock()
        mock_run_result.returncode = 0
        mock_run_result.stdout = 'bswan\n'  # Wrong user - setuid didn't work
        mock_subprocess_run.return_value = mock_run_result
        
        # Mock config file with listener enabled
        config_data = {
            'listener': {
                'enabled': True,
                'host': 'localhost',
                'port': 9876,
                'user': 'cadtools'
            }
        }
        
        with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
            # Mock successful socket connection to listener
            mock_socket = MagicMock()
            mock_socket_class.return_value = mock_socket
            
            result = executor.initialize_executor()
            
            # Should fall back to listener mode
            self.assertTrue(result)
            self.assertEqual(executor.get_execution_mode(), 'listener')
    
    @patch('lib.executor.os.path.exists')
    @patch('lib.executor.logger')
    @patch('lib.executor.socket.socket')
    def test_initialize_executor_listener_mode(self, mock_socket_class, mock_logger, mock_exists):
        """Test initialization with listener when setuid binary not available"""
        # Mock setuid binary doesn't exist
        def exists_side_effect(path):
            if 'sudo' in path:
                return False
            elif 'cadinstall.json' in path:
                return True
            return False
        
        mock_exists.side_effect = exists_side_effect
        
        # Mock config file
        config_data = {
            'listener': {
                'enabled': True,
                'host': 'localhost',
                'port': 9876,
                'user': 'cadtools'
            }
        }
        
        with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
            # Mock successful socket connection
            mock_socket = MagicMock()
            mock_socket_class.return_value = mock_socket
            
            result = executor.initialize_executor()
            
            self.assertTrue(result)
            self.assertEqual(executor.get_execution_mode(), 'listener')
            self.assertIsNotNone(executor.get_listener_config())
    
    @patch('lib.executor.os.path.exists')
    @patch('lib.executor.logger')
    def test_initialize_executor_no_config(self, mock_logger, mock_exists):
        """Test initialization failure when no setuid and no config"""
        # Mock both setuid binary and config don't exist
        mock_exists.return_value = False
        
        with self.assertRaises(SystemExit):
            executor.initialize_executor()
    
    @patch('lib.executor.os.path.exists')
    @patch('lib.executor.logger')
    @patch('lib.executor.socket.socket')
    def test_initialize_executor_listener_not_enabled(self, mock_socket_class, mock_logger, mock_exists):
        """Test initialization failure when listener not enabled"""
        # Mock setuid binary doesn't exist, config exists
        def exists_side_effect(path):
            if 'sudo' in path:
                return False
            elif 'cadinstall.json' in path:
                return True
            return False
        
        mock_exists.side_effect = exists_side_effect
        
        # Mock config with listener disabled
        config_data = {
            'listener': {
                'enabled': False,
                'host': 'localhost',
                'port': 9876
            }
        }
        
        with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
            with self.assertRaises(SystemExit):
                executor.initialize_executor()
    
    @patch('lib.executor.os.path.exists')
    @patch('lib.executor.logger')
    @patch('lib.executor.socket.socket')
    def test_initialize_executor_listener_not_accessible(self, mock_socket_class, mock_logger, mock_exists):
        """Test initialization failure when listener not accessible"""
        # Mock setuid binary doesn't exist, config exists
        def exists_side_effect(path):
            if 'sudo' in path:
                return False
            elif 'cadinstall.json' in path:
                return True
            return False
        
        mock_exists.side_effect = exists_side_effect
        
        # Mock config with listener enabled
        config_data = {
            'listener': {
                'enabled': True,
                'host': 'localhost',
                'port': 9876,
                'user': 'cadtools'
            }
        }
        
        with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
            # Mock socket connection failure
            mock_socket = MagicMock()
            mock_socket.connect.side_effect = socket.error("Connection refused")
            mock_socket_class.return_value = mock_socket
            
            with self.assertRaises(SystemExit):
                executor.initialize_executor()
    
    def test_get_execution_mode_not_initialized(self):
        """Test getting execution mode before initialization"""
        with self.assertRaises(SystemExit):
            executor.get_execution_mode()
    
    @patch('lib.executor.os.path.exists')
    @patch('lib.executor.os.stat')
    @patch('lib.executor.logger')
    def test_get_sudo_path(self, mock_logger, mock_stat, mock_exists):
        """Test getting sudo path in setuid mode"""
        # Initialize in setuid mode
        mock_exists.return_value = True
        mock_stat_result = MagicMock()
        mock_stat_result.st_mode = 0o104755
        mock_stat.return_value = mock_stat_result
        
        executor.initialize_executor()
        
        sudo_path = executor.get_sudo_path()
        self.assertIsNotNone(sudo_path)
        self.assertIn('.sudo', sudo_path)
    
    @patch('lib.executor.os.path.exists')
    @patch('lib.executor.logger')
    @patch('lib.executor.socket.socket')
    def test_send_command_to_listener(self, mock_socket_class, mock_logger, mock_exists):
        """Test sending command to listener"""
        # Initialize in listener mode
        def exists_side_effect(path):
            if 'sudo' in path:
                return False
            elif 'cadinstall.json' in path:
                return True
            return False
        
        mock_exists.side_effect = exists_side_effect
        
        config_data = {
            'listener': {
                'enabled': True,
                'host': 'localhost',
                'port': 9876,
                'user': 'cadtools'
            }
        }
        
        with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
            # Mock successful socket connection during initialization
            mock_init_socket = MagicMock()
            
            # Mock socket for sending command
            mock_command_socket = MagicMock()
            
            # Mock response from listener
            response_data = [
                json.dumps({'type': 'stdout', 'data': 'test output'}).encode('utf-8') + b'\n',
                json.dumps({'type': 'exit_code', 'data': 0}).encode('utf-8') + b'\n'
            ]
            mock_command_socket.recv.side_effect = response_data + [b'']
            
            # Configure socket class to return different sockets
            mock_socket_class.side_effect = [mock_init_socket, mock_command_socket]
            
            executor.initialize_executor()
            
            # Send command
            exit_code, stdout_lines = executor.send_command_to_listener('/bin/ls')
            
            self.assertEqual(exit_code, 0)
            self.assertEqual(stdout_lines, ['test output'])
            mock_command_socket.sendall.assert_called_once()
    
    @patch('lib.executor.os.path.exists')
    @patch('lib.executor.logger')
    @patch('lib.executor.socket.socket')
    def test_send_command_socket_error(self, mock_socket_class, mock_logger, mock_exists):
        """Test error handling when socket fails"""
        # Initialize in listener mode
        def exists_side_effect(path):
            if 'sudo' in path:
                return False
            elif 'cadinstall.json' in path:
                return True
            return False
        
        mock_exists.side_effect = exists_side_effect
        
        config_data = {
            'listener': {
                'enabled': True,
                'host': 'localhost',
                'port': 9876,
                'user': 'cadtools'
            }
        }
        
        with patch('builtins.open', mock_open(read_data=json.dumps(config_data))):
            # Mock successful socket connection during initialization
            mock_init_socket = MagicMock()
            
            # Mock socket that fails when sending command
            mock_command_socket = MagicMock()
            mock_command_socket.connect.side_effect = socket.error("Connection refused")
            
            mock_socket_class.side_effect = [mock_init_socket, mock_command_socket]
            
            executor.initialize_executor()
            
            # Send command
            exit_code, stdout_lines = executor.send_command_to_listener('/bin/ls')
            
            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout_lines, [])


if __name__ == '__main__':
    unittest.main()

