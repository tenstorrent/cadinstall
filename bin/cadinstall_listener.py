#!/usr/bin/python3
# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

"""
Cadinstall Listener Daemon

This daemon listens on a configured port and executes commands as the configured user.
It serves as a replacement for the setuid binary when setuid functionality is not available
(e.g., in containers or on fileservers with setuid disabled).
"""

import socket
import json
import subprocess
import sys
import os
import logging
import argparse
import signal
import threading
from datetime import datetime

# Set up argument parser
parser = argparse.ArgumentParser(description='Cadinstall Listener Daemon')
parser.add_argument('--config', default='/tools_vendor/FOSS/cadinstall/2.0/config/cadinstall.json',
                    help='Path to configuration file')
parser.add_argument('--logfile', help='Override log file from config')
parser.add_argument('--host', help='Override host from config')
parser.add_argument('--port', type=int, help='Override port from config')
args = parser.parse_args()

# Load configuration
config_path = args.config
if not os.path.exists(config_path):
    # Try relative path from script location
    script_dir = os.path.dirname(os.path.realpath(__file__))
    config_path = os.path.join(script_dir, '..', 'config', 'cadinstall.json')
    
if not os.path.exists(config_path):
    print("ERROR: Configuration file not found: %s" % config_path, file=sys.stderr)
    sys.exit(1)

try:
    with open(config_path, 'r') as f:
        config = json.load(f)
except Exception as e:
    print("ERROR: Failed to load configuration: %s" % str(e), file=sys.stderr)
    sys.exit(1)

# Get listener configuration
listener_config = config.get('listener', {})
HOST = args.host or listener_config.get('host', 'localhost')
PORT = args.port or listener_config.get('port', 9876)
LOG_FILE = args.logfile or listener_config.get('logfile', '/tmp/cadinstall_listener.log')
CONFIGURED_USER = listener_config.get('user', 'cadtools')

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('cadinstall_listener')

# Load allowed commands
ALLOWED_COMMANDS_FILE = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + '/../etc/allowed_commands')
if not os.path.exists(ALLOWED_COMMANDS_FILE):
    logger.error("Allowed commands file not found: %s" % ALLOWED_COMMANDS_FILE)
    sys.exit(1)

allowed_commands = []
with open(ALLOWED_COMMANDS_FILE, 'r') as f:
    for line in f:
        allowed_commands.append(line.rstrip())

logger.info("Loaded %d allowed commands from %s" % (len(allowed_commands), ALLOWED_COMMANDS_FILE))

def is_command_allowed(command):
    """Check if the command is in the allowed commands list"""
    # Extract the base command (first part before any arguments)
    cmd_parts = command.split()
    if not cmd_parts:
        return False
    
    base_command = cmd_parts[0]
    return base_command in allowed_commands

def execute_command(command, hostname, client_socket):
    """
    Execute a command and stream output back to the client.
    Commands are executed via SSH to the specified hostname to ensure
    access to local filesystems (containers, /tmp, etc).
    Returns exit code.
    """
    # Wrap command with SSH to the originating hostname
    # This ensures commands run in the context where local filesystems are accessible
    ssh_command = "/usr/bin/ssh %s '%s'" % (hostname, command.replace("'", "'\\''"))
    
    logger.info("Executing command on %s: %s" % (hostname, command))
    
    try:
        # Start the process (using SSH to originating host)
        process = subprocess.Popen(
            ssh_command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            universal_newlines=False
        )
        
        # Read stdout and stderr in real-time
        def read_stream(stream, stream_type):
            """Read from a stream and send to client"""
            try:
                for line in iter(stream.readline, b''):
                    if line:
                        response = {
                            'type': stream_type,
                            'data': line.decode('utf-8', errors='replace').rstrip()
                        }
                        try:
                            client_socket.sendall(json.dumps(response).encode('utf-8') + b'\n')
                        except Exception as e:
                            logger.error("Failed to send %s to client: %s" % (stream_type, str(e)))
                            break
            except Exception as e:
                logger.error("Error reading %s: %s" % (stream_type, str(e)))
        
        # Create threads to read stdout and stderr simultaneously
        stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, 'stdout'))
        stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, 'stderr'))
        
        stdout_thread.start()
        stderr_thread.start()
        
        # Wait for the process to complete
        process.wait()
        
        # Wait for threads to finish
        stdout_thread.join()
        stderr_thread.join()
        
        exit_code = process.returncode
        logger.info("Command completed with exit code: %d" % exit_code)
        
        # Send exit code
        response = {
            'type': 'exit_code',
            'data': exit_code
        }
        client_socket.sendall(json.dumps(response).encode('utf-8') + b'\n')
        
        return exit_code
        
    except Exception as e:
        logger.error("Error executing command: %s" % str(e))
        error_response = {
            'type': 'error',
            'data': str(e)
        }
        try:
            client_socket.sendall(json.dumps(error_response).encode('utf-8') + b'\n')
        except:
            pass
        return 1

def handle_client(client_socket, client_address):
    """Handle a client connection"""
    logger.info("New connection from %s:%d" % client_address)
    
    try:
        # Receive the command request
        data = b''
        while True:
            chunk = client_socket.recv(4096)
            if not chunk:
                break
            data += chunk
            if b'\n' in data:
                break
        
        if not data:
            logger.warning("No data received from client")
            return
        
        # Parse the request
        try:
            request = json.loads(data.decode('utf-8').strip())
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON received: %s" % str(e))
            error_response = {
                'type': 'error',
                'data': 'Invalid JSON request'
            }
            client_socket.sendall(json.dumps(error_response).encode('utf-8') + b'\n')
            return
        
        command = request.get('command')
        hostname = request.get('hostname')
        
        if not command:
            logger.error("No command in request")
            error_response = {
                'type': 'error',
                'data': 'No command specified'
            }
            client_socket.sendall(json.dumps(error_response).encode('utf-8') + b'\n')
            return
        
        if not hostname:
            logger.error("No hostname in request")
            error_response = {
                'type': 'error',
                'data': 'No hostname specified'
            }
            client_socket.sendall(json.dumps(error_response).encode('utf-8') + b'\n')
            return
        
        # Check if command is allowed
        if not is_command_allowed(command):
            logger.error("Command not allowed: %s" % command)
            error_response = {
                'type': 'error',
                'data': 'Command not allowed: %s' % command
            }
            client_socket.sendall(json.dumps(error_response).encode('utf-8') + b'\n')
            return
        
        # Execute the command (via SSH to originating hostname)
        execute_command(command, hostname, client_socket)
        
    except Exception as e:
        logger.error("Error handling client: %s" % str(e))
    finally:
        client_socket.close()
        logger.info("Connection closed for %s:%d" % client_address)

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    logger.info("Received signal %d, shutting down..." % sig)
    sys.exit(0)

def main():
    """Main listener loop"""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("=" * 80)
    logger.info("Cadinstall Listener Daemon Starting")
    logger.info("Configuration file: %s" % config_path)
    logger.info("Listening on %s:%d" % (HOST, PORT))
    logger.info("Log file: %s" % LOG_FILE)
    logger.info("Configured user: %s" % CONFIGURED_USER)
    logger.info("=" * 80)
    
    # Create socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(5)
        logger.info("Listener started successfully")
        
        while True:
            client_socket, client_address = server_socket.accept()
            # Handle each client in a separate thread
            client_thread = threading.Thread(
                target=handle_client,
                args=(client_socket, client_address)
            )
            client_thread.daemon = True
            client_thread.start()
            
    except OSError as e:
        logger.error("Socket error: %s" % str(e))
        logger.error("Make sure the port %d is not already in use" % PORT)
        sys.exit(1)
    except Exception as e:
        logger.error("Unexpected error: %s" % str(e))
        sys.exit(1)
    finally:
        server_socket.close()
        logger.info("Listener stopped")

if __name__ == '__main__':
    main()

