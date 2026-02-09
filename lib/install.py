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
    ## get the logfile location
    log_file = lib.my_globals.get_log_file()
    if log_file:
        f.write("Logfile: %s\n" % log_file)
    ## get the full command with resolved paths
    full_command = lib.my_globals.get_full_command()
    if full_command:
        f.write("Command: %s\n" % full_command)
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

def delete_tool(vendor, tool, version, dest_host, dest):
    """
    Delete a previously installed vendor/tool/version from the specified destination.

    This function enforces strict safety controls:
      1. vendor, tool, and version must all be fully defined directory names
         (validated by regex — no empty strings, no ".", no "..").
      2. The installation metadata file (.cadinstall.metadata) must exist and
         must contain the installing user's name; only that user may delete.
      3. The deletion must occur within ``delete_time_limit`` minutes of the
         original installation time.
      4. The caller must interactively type "DELETE" (all caps) to confirm.
      5. Pretend mode reports whether all conditions are met but does not
         actually remove anything.

    Args:
        vendor:    The vendor name (e.g. "synopsys").
        tool:      The tool name (e.g. "vcs").
        version:   The version string (e.g. "2023.12").
        dest_host: The host with write access to /tools_vendor (from siteHash).
        dest:      The full destination path
                   (e.g. /tools_vendor/synopsys/vcs/2023.12).

    Returns:
        0 on success, exits the program on any failure.
    """
    import re

    pretend = lib.my_globals.get_pretend()

    # ------------------------------------------------------------------ #
    # 1. Validate vendor / tool / version with a strict regex            #
    #    Each component must be a non-empty string that does NOT consist  #
    #    solely of dots (blocks ".", "..", and sneaky "..." etc.) and     #
    #    does not contain path separators or whitespace.                  #
    # ------------------------------------------------------------------ #
    path_component_re = re.compile(r'^(?!\.+$)[A-Za-z0-9][A-Za-z0-9._-]*$')

    for label, value in [('vendor', vendor), ('tool', tool), ('version', version)]:
        if not value or not path_component_re.match(value):
            logger.error("Invalid %s value: '%s'. "
                         "Each of --vendor, --tool, and --version must be a "
                         "non-empty, valid directory name (no dots-only, no "
                         "path separators, no whitespace)." % (label, value))
            sys.exit(1)

    logger.info("Delete request for %s/%s/%s on %s" % (vendor, tool, version, dest_host))

    # ------------------------------------------------------------------ #
    # 2. Verify the installation directory actually exists                #
    # ------------------------------------------------------------------ #
    is_local = (check_same_host(dest_host) == 0)

    if not pretend:
        if is_local:
            test_command = "/bin/test -d %s" % dest
        else:
            test_command = "/usr/bin/ssh %s /bin/test -d %s" % (dest_host, dest)

        test_status = run_command(test_command)
        if test_status != 0:
            logger.error("Destination directory does not exist: %s on %s" % (dest, dest_host))
            sys.exit(1)
    else:
        logger.info("Pretend mode: would verify destination directory exists: %s on %s" % (dest, dest_host))

    # ------------------------------------------------------------------ #
    # 3. Read and parse the metadata file                                #
    # ------------------------------------------------------------------ #
    metadata_file = dest + "/.cadinstall.metadata"
    metadata_contents = None

    if not pretend:
        if is_local:
            cat_command = "/bin/cat %s" % metadata_file
        else:
            cat_command = "/usr/bin/ssh %s /bin/cat %s" % (dest_host, metadata_file)

        status, output = run_command_with_output(cat_command, force_run=False)
        if status != 0 or not output.strip():
            logger.error("Cannot read metadata file: %s on %s" % (metadata_file, dest_host))
            logger.error("Without the metadata file the installing user and install time "
                         "cannot be determined. Deletion is not allowed.")
            sys.exit(1)
        metadata_contents = output.strip()
    else:
        # In pretend mode we still try to read the metadata so we can
        # report whether the conditions *would* be met.
        if is_local:
            cat_command = "/bin/cat %s" % metadata_file
        else:
            cat_command = "/usr/bin/ssh %s /bin/cat %s" % (dest_host, metadata_file)

        status, output = run_command_with_output(cat_command, force_run=True)
        if status != 0 or not output.strip():
            logger.error("Cannot read metadata file: %s on %s" % (metadata_file, dest_host))
            logger.error("Without the metadata file the installing user and install time "
                         "cannot be determined. Deletion would not be allowed.")
            sys.exit(1)
        metadata_contents = output.strip()

    # Parse key fields from the metadata file
    installed_by = None
    installed_on = None
    for line in metadata_contents.splitlines():
        if line.startswith("Installed by:"):
            installed_by = line.split(":", 1)[1].strip()
        elif line.startswith("Installed on:"):
            installed_on = line.split(":", 1)[1].strip()

    # ------------------------------------------------------------------ #
    # 4. Verify the current user is the one who performed the install    #
    # ------------------------------------------------------------------ #
    current_user = getpass.getuser()

    if not installed_by:
        logger.error("Could not determine the installing user from the metadata file.")
        logger.error("Deletion is not allowed.")
        sys.exit(1)

    if current_user != installed_by:
        logger.error("Deletion is only permitted by the user who performed the installation.")
        logger.error("Current user : %s" % current_user)
        logger.error("Installed by : %s" % installed_by)
        sys.exit(1)

    logger.info("User check passed: current user '%s' matches installing user '%s'" %
                (current_user, installed_by))

    # ------------------------------------------------------------------ #
    # 5. Verify the deletion is within the allowed time window           #
    # ------------------------------------------------------------------ #
    if not installed_on:
        logger.error("Could not determine the installation timestamp from the metadata file.")
        logger.error("Deletion is not allowed.")
        sys.exit(1)

    try:
        install_time = datetime.strptime(installed_on, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        # Try without microseconds
        try:
            install_time = datetime.strptime(installed_on, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            logger.error("Could not parse installation timestamp: '%s'" % installed_on)
            logger.error("Deletion is not allowed.")
            sys.exit(1)

    from lib.tool_defs import delete_time_limit
    elapsed = datetime.now() - install_time
    elapsed_minutes = elapsed.total_seconds() / 60.0

    if elapsed_minutes > delete_time_limit:
        logger.error("Deletion time window has expired.")
        logger.error("Installed on       : %s" % installed_on)
        logger.error("Current time       : %s" % datetime.now())
        logger.error("Elapsed            : %.1f minutes" % elapsed_minutes)
        logger.error("Allowed time limit : %d minutes" % delete_time_limit)
        sys.exit(1)

    logger.info("Time check passed: %.1f minutes elapsed (limit: %d minutes)" %
                (elapsed_minutes, delete_time_limit))

    # ------------------------------------------------------------------ #
    # 6. Interactive confirmation — user must type DELETE                 #
    # ------------------------------------------------------------------ #
    if pretend:
        logger.info("Pretend mode: all conditions are met. In a real run the user "
                     "would be prompted to type 'DELETE' to confirm removal of:")
        logger.info("  %s on %s" % (dest, dest_host))
        logger.info("Pretend mode: no actual removal performed.")
        return 0

    logger.info("")
    logger.info("=" * 70)
    logger.info("WARNING: You are about to permanently delete:")
    logger.info("  %s on %s" % (dest, dest_host))
    logger.info("")
    logger.info("Type DELETE (all caps) to confirm: ")
    logger.info("=" * 70)

    try:
        confirmation = input("Confirm deletion by typing DELETE: ")
    except (EOFError, KeyboardInterrupt):
        logger.error("\nDeletion cancelled.")
        sys.exit(1)

    if confirmation != "DELETE":
        logger.error("Confirmation failed. You typed '%s' instead of 'DELETE'." % confirmation)
        logger.error("Deletion cancelled.")
        sys.exit(1)

    logger.info("Confirmation accepted. Proceeding with deletion ...")

    # ------------------------------------------------------------------ #
    # 7. Perform the actual removal                                      #
    # ------------------------------------------------------------------ #
    if is_local:
        rm_command = "/usr/bin/rm -rf %s" % dest
    else:
        rm_command = "/usr/bin/ssh %s /usr/bin/rm -rf %s" % (dest_host, dest)

    status = run_command(rm_command)

    if status != 0:
        logger.error("Something failed during the deletion. Exiting ...")
        sys.exit(1)

    logger.info("Successfully deleted %s/%s/%s on %s" % (vendor, tool, version, dest_host))
    return 0


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

