# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

import os
import pwd
import sys
import subprocess
import logging
import lib.my_globals
from lib.executor import get_execution_mode, get_sudo_path, send_command_to_listener

logger = logging.getLogger('cadinstall')

def run_command(command, pretend=False):
    allowed_commands_file = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + '/../etc/allowed_commands')

    pretend = lib.my_globals.get_pretend()

    # Get the execution mode
    execution_mode = get_execution_mode()
    
    # Build an array with every line from the allowed_commands file
    allowed_commands = []
    with open(allowed_commands_file, 'r') as f:
        for line in f:
            allowed_commands.append(line.rstrip())

    # If using listener mode, send the command directly to the listener
    if execution_mode == 'listener':
        if pretend:
            if lib.my_globals.get_vv():
                logger.info("Because the '-p' switch was thrown, not actually running command: %s" % command)
            else:
                logger.info("Because the '-p' switch was thrown, not actually running command: %s" % command)
            return 0
        else:
            if lib.my_globals.get_vv():
                logger.info("Running command via listener: %s" % command)
            else:
                logger.info("Running command: %s" % command)
            
            exit_code, _ = send_command_to_listener(command)
            return exit_code
    
    # Otherwise, use setuid mode (original logic)
    sudo = get_sudo_path()
    sudo_command = command

    # Special handling for remote rsync commands with --rsync-path
    if "--rsync-path=" in command and ":" in command:
        # This is a remote rsync command, handle rsync-path specially
        import re
        # Extract the rsync-path content
        rsync_path_match = re.search(r"--rsync-path='([^']*)'", command)
        if rsync_path_match:
            original_rsync_path = rsync_path_match.group(1)
            # The remote commands in rsync-path don't need .sudo wrapping
            # The rsync connection itself is authenticated via SSH
            modified_rsync_path = original_rsync_path
            
            # Temporarily replace the rsync-path with a placeholder to avoid double processing
            placeholder = "RSYNC_PATH_PLACEHOLDER"
            command_without_rsync_path = command.replace(f"--rsync-path='{original_rsync_path}'", placeholder)
            
            # Apply normal .sudo replacement to the rest of the command
            for allowed_command in allowed_commands:
                command_without_rsync_path = command_without_rsync_path.replace(allowed_command, sudo + ' ' + allowed_command)
            
            # Put the modified rsync-path back
            sudo_command = command_without_rsync_path.replace(placeholder, f"--rsync-path='{modified_rsync_path}'")
        else:
            # Fallback to normal processing if regex doesn't match
            for allowed_command in allowed_commands:
                sudo_command = sudo_command.replace(allowed_command, sudo + ' ' + allowed_command)
    # Special handling for SSH commands to remote hosts
    elif command.startswith('/usr/bin/ssh '):
        # This is an SSH command - only wrap the SSH command itself with .sudo
        # The remote commands don't need .sudo wrapping because SSH authentication handles it
        sudo_command = sudo_command.replace('/usr/bin/ssh', sudo + ' /usr/bin/ssh')
    else:
        # Normal processing for non-remote rsync commands
        for allowed_command in allowed_commands:
            sudo_command = sudo_command.replace(allowed_command, sudo + ' ' + allowed_command)

    if pretend:
        if lib.my_globals.get_vv():
            logger.info("Because the '-p' switch was thrown, not actually running sudo_command: %s" % sudo_command)
        else:
            logger.info("Because the '-p' switch was thrown, not actually running command: %s" % command)
        return(0)
    else:
        if lib.my_globals.get_vv():
            logger.info("Running sudo_command: %s" % sudo_command)
        else:
            logger.info("Running command: %s" % command)

        from subprocess import PIPE, Popen
        return_code = 0
        with Popen(sudo_command, shell=True, stdout=PIPE, stderr=PIPE, bufsize=1) as process:
            for line in process.stdout:
                logger.info(line.decode('utf-8').rstrip())
            for line in process.stderr:
                logger.error(line.decode('utf-8').rstrip())

        process.wait()
        if process.returncode:
            return_code = process.returncode
            logger.info("Return code: %s" % return_code)
            
    return(return_code)    


def run_command_with_output(command, pretend=False):
    """
    Run a command through the setuid binary or listener and return both status and output.
    Similar to run_command() but captures and returns stdout.
    """
    allowed_commands_file = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + '/../etc/allowed_commands')

    pretend = lib.my_globals.get_pretend()

    # Get the execution mode
    execution_mode = get_execution_mode()
    
    # Build an array with every line from the allowed_commands file
    allowed_commands = []
    with open(allowed_commands_file, 'r') as f:
        for line in f:
            allowed_commands.append(line.rstrip())

    # If using listener mode, send the command directly to the listener
    if execution_mode == 'listener':
        if pretend:
            if lib.my_globals.get_vv():
                logger.info("Because the '-p' switch was thrown, not actually running command: %s" % command)
            else:
                logger.info("Because the '-p' switch was thrown, not actually running command: %s" % command)
            return 0, ""
        else:
            if lib.my_globals.get_vv():
                logger.info("Running command via listener: %s" % command)
            else:
                logger.info("Running command: %s" % command)
            
            exit_code, stdout_lines = send_command_to_listener(command)
            return exit_code, '\n'.join(stdout_lines)
    
    # Otherwise, use setuid mode (original logic)
    sudo = get_sudo_path()
    sudo_command = command

    # Apply .sudo replacement to allowed commands
    # Special handling for SSH commands - only wrap the SSH command itself
    if command.startswith('/usr/bin/ssh '):
        sudo_command = sudo_command.replace('/usr/bin/ssh', sudo + ' /usr/bin/ssh')
    else:
        for allowed_command in allowed_commands:
            sudo_command = sudo_command.replace(allowed_command, sudo + ' ' + allowed_command)

    if pretend:
        if lib.my_globals.get_vv():
            logger.info("Because the '-p' switch was thrown, not actually running sudo_command: %s" % sudo_command)
        else:
            logger.info("Because the '-p' switch was thrown, not actually running command: %s" % command)
        return(0, "")  # Return success and empty output for pretend mode
    else:
        if lib.my_globals.get_vv():
            logger.info("Running sudo_command: %s" % sudo_command)
        else:
            logger.info("Running command: %s" % command)

        from subprocess import PIPE, Popen
        return_code = 0
        stdout_lines = []
        
        with Popen(sudo_command, shell=True, stdout=PIPE, stderr=PIPE, bufsize=1) as process:
            for line in process.stdout:
                line_str = line.decode('utf-8').rstrip()
                logger.info(line_str)
                stdout_lines.append(line_str)
            for line in process.stderr:
                logger.error(line.decode('utf-8').rstrip())

        process.wait()
        if process.returncode:
            return_code = process.returncode
            logger.info("Return code: %s" % return_code)
            
        return(return_code, '\n'.join(stdout_lines))


def check_src(src):
    logger.info("Verifying source directory exists %s and is readable to %s ..." % (src,lib.tool_defs.cadtools_user))

    if lib.my_globals.get_pretend():
        return(0)

    if not os.path.exists(src):
        logger.error("Source directory does not exist: %s" % src)
        sys.exit(1)
    
    command = "/bin/test -r " + src 
    status = run_command(command)
    if status != 0:
        logger.error("Source directory %s is not readable to %s" % (src,lib.tool_defs.cadtools_user))
        sys.exit(1)

    return(0)
    

def check_dest(dest, host=None):
    exists = 0
    if host:
        logger.info("Checking %s for %s ..." % (host, dest))
        
        # Use local check if same domain, SSH if different domain
        if check_domain(host) == 0:
            # Local domain - check locally
            if os.path.exists(dest):
                logger.error("Destination directory already exists: %s" % dest)
                exists=1
                sys.exit(1)
        else:
            # Remote domain - use SSH through setuid binary
            if lib.my_globals.get_pretend():
                logger.info("Pretend mode: would check if destination exists on remote host %s: %s" % (host, dest))
                # In pretend mode, assume destination doesn't exist to allow planning
                exists = 0
            else:
                command = "/usr/bin/ssh %s /usr/bin/ls -ltrd %s" % (host, dest)
                status, output = run_command_with_output(command)
                if status == 0 and output.strip():
                    logger.error("Destination directory already exists on %s : %s" % (host, dest))
                    exists = 1
                    sys.exit(1)
    else:
        if os.path.exists(dest):
            logger.error("Destination directory already exists: %s" % dest)
            exists=1

    return(exists)

def check_domain(dest):
    ## check that the 'dest' string contains '.tenstorrent.com'
    if '.tenstorrent.com' not in dest:
        logger.error("The target machine %s is does not contain the tenstorrent.com domain" % dest)
        return(1)

    ## Get the domain of the current machine
    command = "/usr/bin/dnsdomainname"
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    domain = process.stdout.read().decode('utf-8').rstrip().split('.')[0]

    ## Get the domain of the dest machine by parsing the dest string by '.tenstorrent.com'
    ## the domain is the first element of the list
    dest_domain = dest.split('.')[1]
    
    ## Check if the domains are the same
    if domain != dest_domain:
        if lib.my_globals.get_vv():
            logger.info("Current machine is in domain %s and target machine is in domain %s" % (domain, dest_domain))
        return(1)
    
    return(0)

def get_directory_size(path):
    """Get the size of a directory in bytes using du command"""
    if not os.path.exists(path):
        logger.error("Source directory does not exist: %s" % path)
        return 0
    
    try:
        # Always calculate real size, even in pretend mode - this is important information
        command = "du -sb %s" % path
        if lib.my_globals.get_pretend():
            logger.info("Pretend mode: calculating actual size of %s for planning purposes" % path)
        
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate()
        
        if process.returncode != 0:
            logger.error("Failed to calculate directory size for %s: %s" % (path, error.decode('utf-8')))
            return 0
        
        # Parse the output - first field is the size in bytes
        size_bytes = int(output.decode('utf-8').split()[0])
        return size_bytes
    except Exception as e:
        logger.error("Error calculating directory size for %s: %s" % (path, str(e)))
        return 0

def get_available_space(path, host=None):
    """Get available disk space at the given path in bytes"""
    try:
        if host and check_domain(host) != 0:
            # Remote host - use SSH to check disk space
            if lib.my_globals.get_pretend():
                logger.info("Pretend mode: calculating actual available space at %s on remote host %s for planning purposes" % (path, host))
            
            # Check the path itself first, or walk up parent directories until we find one that exists
            current_path = path
            while current_path and current_path != '/':
                command = "/usr/bin/ssh %s /usr/bin/df -B1 %s" % (host, current_path)
                status, output = run_command_with_output(command)
                
                if status == 0:
                    # Success! Found an existing path
                    if current_path != path:
                        logger.info("Using existing parent directory %s for space calculation" % current_path)
                    
                    # Parse df output - available space is the 4th column (index 3)
                    lines = output.strip().split('\n')
                    if len(lines) >= 2:
                        fields = lines[1].split()
                        if len(fields) >= 4:
                            available_bytes = int(fields[3])
                            return available_bytes
                    break
                else:
                    # Path doesn't exist, try parent directory
                    parent_path = os.path.dirname(current_path)
                    if parent_path == current_path:  # Reached root or can't go higher
                        logger.error("Failed to find accessible directory for space check on %s" % host)
                        return 0
                    current_path = parent_path
                    logger.info("Path doesn't exist, trying parent directory %s" % parent_path)
            
            # If we get here, something went wrong
            return 0
        else:
            # Local host - always calculate real available space, even in pretend mode
            if lib.my_globals.get_pretend():
                logger.info("Pretend mode: calculating actual available space at %s for planning purposes" % path)
            
            parent_path = os.path.dirname(path) if not os.path.exists(path) else path
            if not os.path.exists(parent_path):
                # Find the closest existing parent directory to check space
                parent_path = '/'
                for part in path.split('/'):
                    if part:
                        test_path = os.path.join(parent_path, part)
                        if os.path.exists(test_path):
                            parent_path = test_path
                        else:
                            break
            
            statvfs = os.statvfs(parent_path)
            available_bytes = statvfs.f_bavail * statvfs.f_frsize
            return available_bytes
    except Exception as e:
        logger.error("Error checking available space for %s on %s: %s" % (path, host or "localhost", str(e)))
        return 0
    
    return 0

def format_bytes(bytes_value):
    """Format bytes into human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return "%.2f %s" % (bytes_value, unit)
        bytes_value /= 1024.0
    return "%.2f PB" % bytes_value

def check_disk_space_precheck(src, sites_list, vendor, tool, version, dest_base):
    """
    Precheck disk space requirements before installation.
    Returns tuple: (success, sites_with_space, sites_without_space)
    """
    from lib.tool_defs import siteHash
    
    logger.info("Performing disk space precheck...")
    
    # Calculate source directory size
    src_size = get_directory_size(src)
    if src_size == 0:
        logger.error("Could not determine source directory size")
        return False, [], []
    
    logger.info("Source directory size: %s" % format_bytes(src_size))
    
    # Add 20% buffer for safety
    required_space = int(src_size * 1.2)
    logger.info("Required space (with 20%% buffer): %s" % format_bytes(required_space))
    
    sites_with_space = []
    sites_without_space = []
    
    for site in sites_list:
        dest_host = siteHash[site]
        dest_path = "%s/%s/%s/%s" % (dest_base, vendor, tool, version)
        
        available_space = get_available_space(dest_path, dest_host)
        
        logger.info("Site %s (%s): Available space: %s" % (site, dest_host, format_bytes(available_space)))
        
        if available_space >= required_space:
            sites_with_space.append(site)
            logger.info("Site %s: SUFFICIENT SPACE" % site)
        else:
            sites_without_space.append(site)
            logger.error("Site %s: INSUFFICIENT SPACE (need %s, have %s)" % 
                        (site, format_bytes(required_space), format_bytes(available_space)))
    
    success = len(sites_without_space) == 0
    return success, sites_with_space, sites_without_space
