# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

from lib.utils import *
from lib.tool_defs import *
import lib.my_globals
import getpass
import socket
import os
from datetime import datetime


import logging
import stat
logger = logging.getLogger('cadinstall')

def install_tool(vendor, tool, version, src, group, dest_host, dest):
    """
    Install a tool to the specified destination.
    
    Args:
        dest_host: The host with write access to /tools_vendor (from siteHash)
    """
    check_src(src)

    if check_dest(dest, dest_host):
        if lib.my_globals.get_force():
            logger.warn("Proceeding anyways because the '--force' switch was thrown")
        else:
            sys.exit(1)
    
    logger.info("Copying %s/%s/%s to %s ..." % (vendor,tool,version,dest_host))

    # Use local rsync if same host, SSH rsync if different host
    # Since /tools_vendor is only writable on specific hosts (siteHash), we must check the actual host
    if check_same_host(dest_host) == 0:
        # Same host - create parent directories first, then use local rsync
        parent_dir = os.path.dirname(dest)
        mkdir_command = "%s -p %s" % (mkdir, parent_dir)
        mkdir_status = run_command(mkdir_command)
        if mkdir_status != 0:
            logger.error("Failed to create parent directory: %s" % parent_dir)
            sys.exit(1)
        
        command = "%s %s --groupmap=\"*:%s\" %s/ %s/" % (rsync, rsync_options, cadtools_group, src, dest)
    else:
        # Different host - use SSH rsync
        command = "%s %s --groupmap=\"*:%s\" --rsync-path=\'%s -p %s && %s\' %s/ %s:%s/" % (rsync, rsync_options, cadtools_group, mkdir, dest, rsync, src, dest_host, dest)
    
    status = run_command(command)

    if status != 0:
        logger.error("Something failed during the installation. Exiting ...")
        sys.exit(1)

    # Always write metadata file, both for local and remote installations
    write_metadata(dest, dest_host)

    return(status)

def write_metadata(dest, dest_host):
    """
    Write installation metadata to the destination directory.
    
    Args:
        dest: The destination directory path
        dest_host: The host with write access to /tools_vendor (from siteHash)
    """
    pid = os.getpid()
    user = getpass.getuser()
    metadata = ".cadinstall.metadata"
    tmp_metadata = "/tmp/%s.%s.%d" % (metadata, user, pid)
    dest_metadata = dest + "/" + metadata
    
    # Always create the temp file locally
    f = open(tmp_metadata, 'w')
    f.write("Installed by: %s\n" % user)
    f.write("Installed on: %s\n" % datetime.now())
    ## get fully qualified hostname
    f.write("Installed from: %s\n" % socket.getfqdn())
    f.close()

    os.system("/usr/bin/chmod 755 %s" % (tmp_metadata))

    # Copy to destination - use local rsync if same host, SSH rsync if different host
    if check_same_host(dest_host) == 0:
        # Same host - use local rsync
        command = "/usr/bin/rsync -avp %s %s" % (tmp_metadata, dest_metadata)
    else:
        # Different host - use SSH rsync
        command = "/usr/bin/rsync -avp %s %s:%s" % (tmp_metadata, dest_host, dest_metadata)
    
    status = run_command(command)

    os.remove(tmp_metadata)
    
    if status == 0:
        logger.info("Created metadata file: %s on %s" % (dest_metadata, dest_host))
    else:
        logger.warning("Failed to create metadata file: %s on %s" % (dest_metadata, dest_host))

def create_link(dest, vendor, tool, version, link, dest_host):
    """
    Create a symlink in /tools_vendor.
    
    Args:
        dest_host: The host with write access to /tools_vendor (from siteHash)
    """
    logger.info("Creating a symlink called %s/%s/%s/%s that points to ./%s ..." % (dest,vendor,tool,link,version))

    # Use local command if same host, SSH if different host
    if check_same_host(dest_host) == 0:
        # Same host - run command locally
        command = "/usr/bin/ln -sfT ./%s %s/%s/%s/%s" % (version,dest,vendor,tool,link)
    else:
        # Different host - use SSH
        command = "/usr/bin/ssh %s /usr/bin/ln -sfT ./%s %s/%s/%s/%s" % (dest_host, version,dest,vendor,tool,link)
    
    status = run_command(command)

    return(status)

def check_module_permissions(vendor, tool, dest_host):
    """
    Check if we have write permissions to create the vendor/tool module directory.
    This checks the first existing parent directory in the path to ensure we can
    create all necessary subdirectories.
    
    Args:
        dest_host: The host with write access to /tools_vendor (from siteHash)
    
    Returns:
        True if permissions are OK, False otherwise.
    """
    logger.info("Checking module directory permissions for %s/%s on %s ..." % (vendor, tool, dest_host))
    
    if lib.my_globals.get_pretend():
        logger.info("Pretend mode: Skipping actual permissions check")
        return True
    
    # Build the full path that needs to be created
    vendor_tool_path = "%s/%s/%s" % (module_path, vendor, tool)
    
    # Find the first existing parent directory by walking up the path
    path_to_check = vendor_tool_path
    while path_to_check != "/" and path_to_check != "":
        # Check if this directory exists
        if check_same_host(dest_host) == 0:
            # Same host - run command locally
            exists_command = "/bin/test -d %s" % path_to_check
        else:
            # Different host - use SSH
            exists_command = "/usr/bin/ssh %s /bin/test -d %s" % (dest_host, path_to_check)
        
        exists_status = run_command(exists_command)
        
        if exists_status == 0:
            # This directory exists, check if it's writable
            if check_same_host(dest_host) == 0:
                # Same host - run command locally
                write_command = "/bin/test -w %s" % path_to_check
            else:
                # Different host - use SSH
                write_command = "/usr/bin/ssh %s /bin/test -w %s" % (dest_host, path_to_check)
            
            write_status = run_command(write_command)
            
            if write_status != 0:
                logger.error("No write permission to create module directory structure. Cannot write to: %s on %s" % (path_to_check, dest_host))
                return False
            else:
                logger.info("Module directory permissions check passed - can write to: %s" % path_to_check)
                return True
        
        # Move up one directory level
        path_to_check = os.path.dirname(path_to_check)
    
    # If we got here, we couldn't find any existing parent directory
    logger.error("Could not find any existing parent directory for module path: %s on %s" % (vendor_tool_path, dest_host))
    return False

def install_module_files(vendor, tool, version, dest_host):
    """
    Install module files for the given vendor/tool/version.
    Creates symlinks pointing to commonModuleFile in the module path.
    
    Args:
        dest_host: The host with write access to /tools_vendor (from siteHash)
    """
    logger.info("Installing module files for %s/%s/%s on %s ..." % (vendor, tool, version, dest_host))
    
    # Create vendor/tool directory structure
    module_dir = "%s/%s/%s" % (module_path, vendor, tool)
    module_file = "%s/%s" % (module_dir, version)
    
    # Determine if we're working locally or remotely (must check actual host, not just domain)
    is_local = (check_same_host(dest_host) == 0)
    
    # Create directory structure if it doesn't exist - use setuid binary through run_command
    if is_local:
        mkdir_command = "/usr/bin/mkdir -p %s" % module_dir
    else:
        mkdir_command = "/usr/bin/ssh %s /usr/bin/mkdir -p %s" % (dest_host, module_dir)
    
    mkdir_status = run_command(mkdir_command)
    if mkdir_status != 0:
        logger.error("Failed to create module directory: %s" % module_dir)
        return mkdir_status
    
    # Check if existing symlink exists before trying to remove it
    if not lib.my_globals.get_pretend():
        if is_local:
            test_command = "/bin/test -f %s" % module_file
        else:
            test_command = "/usr/bin/ssh %s /bin/test -f %s" % (dest_host, module_file)
        
        test_status = run_command(test_command)
        if test_status == 0:
            # File exists, remove it - use setuid binary through run_command  
            if is_local:
                rm_command = "/usr/bin/rm -f %s" % module_file
            else:
                rm_command = "/usr/bin/ssh %s /usr/bin/rm -f %s" % (dest_host, module_file)
            
            rm_status = run_command(rm_command)
            if rm_status != 0:
                logger.warning("Failed to remove existing module file: %s" % module_file)
            else:
                logger.info("Removed existing module file: %s" % module_file)
    
    # Create symlink to commonModuleFile - use setuid binary through run_command
    if is_local:
        ln_command = "/usr/bin/ln -sf commonModuleFile %s" % module_file
    else:
        ln_command = "/usr/bin/ssh %s /usr/bin/ln -sf commonModuleFile %s" % (dest_host, module_file)
    
    ln_status = run_command(ln_command)
    if ln_status != 0:
        logger.error("Failed to create module symlink: %s" % module_file)
        return ln_status
    
    # Verify the symlink was actually created (skip in pretend mode)
    if not lib.my_globals.get_pretend():
        if is_local:
            verify_command = "/bin/test -L %s" % module_file
        else:
            verify_command = "/usr/bin/ssh %s /bin/test -L %s" % (dest_host, module_file)
        
        verify_status = run_command(verify_command)
        if verify_status != 0:
            logger.error("Module symlink creation failed - symlink does not exist: %s" % module_file)
            return verify_status
        
        logger.info("Created module symlink: %s -> commonModuleFile" % module_file)
    
    return 0

