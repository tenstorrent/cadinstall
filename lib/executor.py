# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

"""
Executor module for cadinstall

This module handles the initialization and management of command execution,
supporting both setuid binary and listener daemon modes.
"""

import os
import sys
import json
import socket
import logging

logger = logging.getLogger('cadinstall')

# Global execution mode
_execution_mode = None  # 'setuid' or 'listener'
_listener_config = None
_sudo_path = None

def initialize_executor():
    """
    Initialize the command executor by checking for setuid binary or listener availability.
    Must be called before any commands are executed.
    Returns True on success, exits the program on failure.
    """
    global _execution_mode, _listener_config, _sudo_path
    
    # Path to setuid binary
    _sudo_path = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + '/../bin/.sudo')
    
    # Check if setuid binary exists and is functional
    if os.path.exists(_sudo_path):
        # Check if it has the setuid bit
        stat_info = os.stat(_sudo_path)
        has_setuid = bool(stat_info.st_mode & 0o4000)
        
        if has_setuid:
            # Setuid bit is set, but we need to verify it actually works
            # (filesystem might be mounted with nosuid option)
            logger.debug("Setuid binary found with setuid bit set: %s" % _sudo_path)
            logger.debug("Testing if setuid binary is functional...")
            
            # Test if setuid actually works by running whoami and checking the result
            try:
                import subprocess
                # Get the owner of the setuid binary
                import pwd
                expected_user = pwd.getpwuid(stat_info.st_uid).pw_name
                
                # Run whoami through the setuid binary
                result = subprocess.run(
                    [_sudo_path, '/usr/bin/whoami'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    timeout=5
                )
                
                actual_user = result.stdout.strip()
                
                # Debug logging
                logger.debug("Setuid test - return code: %d" % result.returncode)
                logger.debug("Setuid test - expected user: %s" % expected_user)
                logger.debug("Setuid test - actual output: '%s'" % actual_user)
                if result.stderr:
                    logger.debug("Setuid test - stderr: %s" % result.stderr.strip())
                
                if result.returncode == 0 and actual_user:
                    if actual_user == expected_user:
                        logger.info("Setuid binary is functional - commands will run as %s" % expected_user)
                        _execution_mode = 'setuid'
                        return True
                    else:
                        logger.debug("Setuid binary is NOT functional - expected user %s but got '%s'" % (expected_user, actual_user))
                        logger.debug("This usually means the filesystem is mounted with 'nosuid' option")
                else:
                    logger.debug("Setuid binary test failed with return code %d" % result.returncode)
                    if result.stderr:
                        logger.debug("Stderr: %s" % result.stderr.strip())
            except Exception as e:
                logger.debug("Failed to test setuid binary functionality: %s" % str(e))
                import traceback
                logger.debug("Exception details: %s" % traceback.format_exc())
        else:
            logger.debug("Setuid binary exists but does not have setuid bit set: %s" % _sudo_path)
    else:
        logger.debug("Setuid binary not found: %s" % _sudo_path)
    
    # Setuid binary not available, check for listener configuration
    logger.debug("Setuid binary not available, checking for listener configuration...")
    
    # Load configuration
    config_path = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + '/../config/cadinstall.json')
    
    if not os.path.exists(config_path):
        logger.error("=" * 80)
        logger.error("ERROR: No valid command execution method available!")
        logger.error("")
        logger.error("The setuid binary is not available and no configuration file was found.")
        logger.error("")
        logger.error("To enable the listener functionality:")
        logger.error("  1. Create configuration file: %s" % config_path)
        logger.error("  2. Enable and configure the listener in the config file")
        logger.error("  3. Start the listener daemon:")
        logger.error("     cadinstall_listener.py --config %s" % config_path)
        logger.error("")
        logger.error("Example configuration:")
        logger.error('  {')
        logger.error('    "listener": {')
        logger.error('      "enabled": true,')
        logger.error('      "host": "localhost",')
        logger.error('      "port": 9876,')
        logger.error('      "user": "cadtools",')
        logger.error('      "logfile": "/var/log/cadinstall_listener.log"')
        logger.error('    }')
        logger.error('  }')
        logger.error("=" * 80)
        sys.exit(1)
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except Exception as e:
        logger.error("Failed to load configuration file %s: %s" % (config_path, str(e)))
        sys.exit(1)
    
    _listener_config = config.get('listener', {})
    
    if not _listener_config.get('enabled', False):
        logger.error("=" * 80)
        logger.error("ERROR: No valid command execution method available!")
        logger.error("")
        logger.error("The setuid binary is not available and the listener is not enabled.")
        logger.error("")
        logger.error("To enable the listener functionality:")
        logger.error("  1. Edit configuration file: %s" % config_path)
        logger.error('  2. Set "enabled": true in the listener section')
        logger.error("  3. Start the listener daemon:")
        logger.error("     cadinstall_listener.py --config %s" % config_path)
        logger.error("=" * 80)
        sys.exit(1)
    
    # Check if listener is accessible
    host = _listener_config.get('host', 'localhost')
    port = _listener_config.get('port', 9876)
    
    logger.debug("Checking listener availability at %s:%d..." % (host, port))
    
    try:
        # Try to connect to the listener
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.settimeout(5)
        test_socket.connect((host, port))
        test_socket.close()
        
        logger.info("Using listener daemon for command execution (commands will run as %s)" % _listener_config.get('user', 'cadtools'))
        _execution_mode = 'listener'
        return True
        
    except (socket.error, socket.timeout) as e:
        logger.error("=" * 80)
        logger.error("ERROR: No valid command execution method available!")
        logger.error("")
        logger.error("The setuid binary is not available and the listener is not accessible.")
        logger.error("")
        logger.error("Listener configuration:")
        logger.error("  Host: %s" % host)
        logger.error("  Port: %d" % port)
        logger.error("  User: %s" % _listener_config.get('user', 'cadtools'))
        logger.error("")
        logger.error("Error: %s" % str(e))
        logger.error("")
        logger.error("To start the listener daemon:")
        logger.error("  cadinstall_listener.py --config %s" % config_path)
        logger.error("")
        logger.error("Make sure the listener is running as the configured user.")
        logger.error("=" * 80)
        sys.exit(1)

def get_execution_mode():
    """Get the current execution mode ('setuid' or 'listener')"""
    if _execution_mode is None:
        logger.error("Executor not initialized. Call initialize_executor() first.")
        sys.exit(1)
    return _execution_mode

def get_listener_config():
    """Get the listener configuration (only valid when using listener mode)"""
    if _execution_mode != 'listener':
        return None
    return _listener_config

def get_sudo_path():
    """Get the path to the sudo binary (only valid when using setuid mode)"""
    if _execution_mode != 'setuid':
        return None
    return _sudo_path

def send_command_to_listener(command):
    """
    Send a command to the listener and receive results in real-time.
    Returns (exit_code, stdout_lines)
    """
    if _execution_mode != 'listener':
        logger.error("Cannot send command to listener - not in listener mode")
        return 1, []
    
    host = _listener_config.get('host', 'localhost')
    port = _listener_config.get('port', 9876)
    
    try:
        # Get the current hostname to pass to listener (so it can SSH back to us)
        import socket as socket_module
        current_hostname = socket_module.getfqdn()
        
        # Connect to listener
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.settimeout(300)  # 5 minute timeout for long operations
        client_socket.connect((host, port))
        
        # Send command with hostname context
        request = {
            'command': command,
            'hostname': current_hostname
        }
        client_socket.sendall(json.dumps(request).encode('utf-8') + b'\n')
        
        # Receive results
        exit_code = 0
        stdout_lines = []
        buffer = b''
        
        while True:
            chunk = client_socket.recv(4096)
            if not chunk:
                break
            
            buffer += chunk
            
            # Process complete lines
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                if not line:
                    continue
                
                try:
                    response = json.loads(line.decode('utf-8'))
                    response_type = response.get('type')
                    data = response.get('data')
                    
                    if response_type == 'stdout':
                        logger.info(data)
                        stdout_lines.append(data)
                    elif response_type == 'stderr':
                        logger.error(data)
                    elif response_type == 'exit_code':
                        exit_code = data
                        if exit_code != 0:
                            logger.info("Return code: %d" % exit_code)
                        # Exit code is the last message
                        client_socket.close()
                        return exit_code, stdout_lines
                    elif response_type == 'error':
                        logger.error("Listener error: %s" % data)
                        client_socket.close()
                        return 1, []
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse listener response: %s" % str(e))
                    continue
        
        client_socket.close()
        return exit_code, stdout_lines
        
    except socket.timeout:
        logger.error("Timeout waiting for listener response")
        return 1, []
    except socket.error as e:
        logger.error("Socket error communicating with listener: %s" % str(e))
        return 1, []
    except Exception as e:
        logger.error("Error communicating with listener: %s" % str(e))
        return 1, []

