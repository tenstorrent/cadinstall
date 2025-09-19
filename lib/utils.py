# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

import os
import pwd
import sys
import subprocess
import logging
import lib.my_globals

logger = logging.getLogger('cadinstall')

def run_command(command, pretend=False):
    sudo = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + '/../bin/.sudo ')
    allowed_commands_file = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + '/../etc/allowed_commands')

    pretend = lib.my_globals.get_pretend()

    sudo_command = command
    ## Build an array with every line from the allowed_commands file
    allowed_commands = []
    with open(allowed_commands_file, 'r') as f:
        for line in f:
            allowed_commands.append(line.rstrip())

    # Special handling for remote rsync commands with --rsync-path
    if "--rsync-path=" in command and ":" in command:
        # This is a remote rsync command, handle rsync-path specially
        import re
        # Extract the rsync-path content
        rsync_path_match = re.search(r"--rsync-path='([^']*)'", command)
        if rsync_path_match:
            original_rsync_path = rsync_path_match.group(1)
            # Replace commands in rsync-path with production .sudo path
            production_sudo = "/tools_vendor/FOSS/cadinstall/2.0/bin/.sudo "
            modified_rsync_path = original_rsync_path
            for allowed_command in allowed_commands:
                modified_rsync_path = modified_rsync_path.replace(allowed_command, production_sudo + allowed_command)
            
            # Temporarily replace the rsync-path with a placeholder to avoid double processing
            placeholder = "RSYNC_PATH_PLACEHOLDER"
            command_without_rsync_path = command.replace(f"--rsync-path='{original_rsync_path}'", placeholder)
            
            # Apply normal .sudo replacement to the rest of the command
            for allowed_command in allowed_commands:
                command_without_rsync_path = command_without_rsync_path.replace(allowed_command, sudo + allowed_command)
            
            # Put the modified rsync-path back
            sudo_command = command_without_rsync_path.replace(placeholder, f"--rsync-path='{modified_rsync_path}'")
        else:
            # Fallback to normal processing if regex doesn't match
            for allowed_command in allowed_commands:
                sudo_command = sudo_command.replace(allowed_command, sudo + allowed_command)
    else:
        # Normal processing for non-remote rsync commands
        for allowed_command in allowed_commands:
            sudo_command = sudo_command.replace(allowed_command, sudo + allowed_command)

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
            # Remote domain - use SSH
            command = "ls -ltrd " + dest
            ssh = subprocess.Popen(["ssh", "%s" % host, command],
                           shell=False,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
            result = ssh.stdout.readlines()
            if result:
                logger.error("Destination directory already exists on %s : %s" % (host,dest))
                exists=1
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
