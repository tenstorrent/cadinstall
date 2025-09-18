# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

from lib.utils import *
from lib.tool_defs import *
import lib.my_globals
import getpass
import socket
from datetime import datetime


import logging
import stat
logger = logging.getLogger('cadinstall')

def install_tool(vendor, tool, version, src, group, dest_host, dest):
    check_src(src)

    if check_dest(dest, dest_host):
        if lib.my_globals.get_force():
            logger.warn("Proceeding anyways because the '--force' switch was thrown")
        else:
            sys.exit(1)
    
    logger.info("Copying %s/%s/%s to %s ..." % (vendor,tool,version,dest_host))

    command = "%s %s --groupmap=\"*:%s\" --rsync-path=\'%s -p %s && %s\' %s/ %s:%s/" % (rsync, rsync_options, cadtools_group, mkdir, dest, rsync, src, dest_host, dest)
    status = run_command(command, lib.my_globals.pretend)

    if status != 0:
        logger.error("Something failed during the installation. Exiting ...")
        sys.exit(1)

    if check_domain(dest_host) == 0:
        write_metadata(dest)

    return(status)

def write_metadata(dest):
    pid = os.getpid()
    user = getpass.getuser()
    metadata = ".cadinstall.metadata"
    tmp_metadata = "/tmp/%s.%s.%d" % (metadata, user, pid)
    dest_metadata = dest + "/" + metadata
    f = open(tmp_metadata, 'w')
    f.write("Installed by: %s\n" % user)
    f.write("Installed on: %s\n" % datetime.now())
    ## get fully qualified hostname
    f.write("Installed from: %s\n" % socket.getfqdn())
    f.close()

    os.system("/usr/bin/chmod 755 %s" % (tmp_metadata))

    command = "/usr/bin/rsync -avp %s %s" % (tmp_metadata, dest_metadata)
    status = run_command(command, lib.my_globals.pretend)

    os.remove(tmp_metadata)

def create_link(dest, vendor, tool, version, link, dest_host):
    logger.info("Creating a symlink called %s/%s/%s/%s that points to ./%s ..." % (dest,vendor,tool,link,version))

    command = "/usr/bin/ssh %s /usr/bin/ln -sfT ./%s %s/%s/%s/%s" % (dest_host, version,dest,vendor,tool,link)
    status = run_command(command, lib.my_globals.pretend)

    return(status)

def check_module_permissions(vendor, tool, dest_host):
    """
    Check if we have write permissions to the vendor/tool module directory.
    Returns True if permissions are OK, False otherwise.
    """
    logger.info("Checking module directory permissions for %s/%s on %s ..." % (vendor, tool, dest_host))
    
    if lib.my_globals.get_pretend():
        logger.info("Pretend mode: Skipping actual permissions check")
        return True
    
    # Check if the vendor/tool directory exists and is writable
    vendor_tool_path = "%s/%s/%s" % (module_path, vendor, tool)
    
    # Use SSH through setuid binary to check permissions on remote host
    command = "/usr/bin/ssh %s /bin/test -w %s" % (dest_host, vendor_tool_path)
    status = run_command(command)
    
    if status != 0:
        logger.error("No write permission to module directory: %s on %s" % (vendor_tool_path, dest_host))
        return False
    
    logger.info("Module directory permissions check passed")
    return True

def install_module_files(vendor, tool, version, dest_host):
    """
    Install module files for the given vendor/tool/version.
    Creates symlinks pointing to commonModuleFile in the module path.
    """
    logger.info("Installing module files for %s/%s/%s on %s ..." % (vendor, tool, version, dest_host))
    
    # Create vendor/tool directory structure
    module_dir = "%s/%s/%s" % (module_path, vendor, tool)
    module_file = "%s/%s" % (module_dir, version)
    
    # Create directory structure if it doesn't exist - use setuid binary through run_command
    mkdir_command = "/usr/bin/ssh %s /usr/bin/mkdir -p %s" % (dest_host, module_dir)
    mkdir_status = run_command(mkdir_command)
    if mkdir_status != 0:
        logger.error("Failed to create module directory: %s" % module_dir)
        return mkdir_status
    
    # Check if existing symlink exists before trying to remove it
    if not lib.my_globals.get_pretend():
        test_command = "/usr/bin/ssh %s /bin/test -f %s" % (dest_host, module_file)
        test_status = run_command(test_command)
        if test_status == 0:
            # File exists, remove it - use setuid binary through run_command  
            rm_command = "/usr/bin/ssh %s /usr/bin/rm -f %s" % (dest_host, module_file)
            rm_status = run_command(rm_command)
            if rm_status != 0:
                logger.warning("Failed to remove existing module file: %s" % module_file)
            else:
                logger.info("Removed existing module file: %s" % module_file)
    
    # Create symlink to commonModuleFile - use setuid binary through run_command
    ln_command = "/usr/bin/ssh %s /usr/bin/ln -sf commonModuleFile %s" % (dest_host, module_file)
    ln_status = run_command(ln_command)
    if ln_status != 0:
        logger.error("Failed to create module symlink: %s" % module_file)
        return ln_status
    
    # Verify the symlink was actually created (skip in pretend mode)
    if not lib.my_globals.get_pretend():
        verify_command = "/usr/bin/ssh %s /bin/test -L %s" % (dest_host, module_file)
        verify_status = run_command(verify_command)
        if verify_status != 0:
            logger.error("Module symlink creation failed - symlink does not exist: %s" % module_file)
            return verify_status
    
    logger.info("Created module symlink: %s -> commonModuleFile" % module_file)
    
    return 0

