# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

from lib.utils import *
from lib.tool_defs import *
import lib.my_globals
import getpass
import socket
import os
import re
from datetime import datetime


import logging
import stat
logger = logging.getLogger('cadinstall')

# Format used for the "Install started on" / "Install completed on" timestamps
# in the .cadinstall.metadata file. Timestamps are recorded in the local
# timezone of the host running cadinstall; the numeric UTC offset (e.g. -0400)
# makes them unambiguous and the trailing name (e.g. EDT) is for readability.
METADATA_TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f %z (%Z)"


def _format_metadata_time(dt):
    """Format a timezone-aware datetime for the metadata file."""
    return dt.strftime(METADATA_TIME_FORMAT)


def _parse_metadata_time(value):
    """
    Parse a timestamp string read back from the metadata file into a datetime.

    Handles the timezone-aware format written by cadinstall
    ('YYYY-MM-DD HH:MM:SS.ffffff -0400 (EDT)') as well as legacy naive
    timestamps ('YYYY-MM-DD HH:MM:SS[.ffffff]') written before timezone
    information was recorded. Returns None if the value cannot be parsed.
    """
    if not value:
        return None
    # Strip a trailing human-readable timezone name annotation like "(EDT)";
    # strptime handling of %Z is unreliable, so we parse the numeric offset only.
    cleaned = re.sub(r'\s*\([^)]*\)\s*$', '', value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f %z",
                "%Y-%m-%d %H:%M:%S %z",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None

def install_tool(vendor, tool, version, src, group, dest_host, dest):
    """
    Install a tool to the specified destination.
    
    Args:
        dest_host: The host with write access to /tools_vendor (from siteHash)

    Note:
        The caller (install subcommand) validates that the destination does not
        already exist for every site up front, before any installation begins.
        The destination directory is also pre-created by write_metadata so the
        deletion metadata is in place before anything is copied in, so this
        function intentionally does not re-run check_dest here.
    """
    check_src(src)

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

    return(status)

def _build_metadata_lines(user, started_on, completed_on=None):
    """
    Build the list of text lines that make up a .cadinstall.metadata file.

    "Install started on" is recorded at the very beginning of an installation so
    that even an interrupted install (network drop, ctrl-c, etc.) leaves behind a
    metadata file the delete subcommand can act on. "Install completed on" is only
    added once the installation has finished successfully.
    """
    lines = []
    lines.append("Installed by: %s\n" % user)
    lines.append("Install started on: %s\n" % _format_metadata_time(started_on))
    if completed_on is not None:
        lines.append("Install completed on: %s\n" % _format_metadata_time(completed_on))
    ## get fully qualified hostname
    lines.append("Installed from: %s\n" % socket.getfqdn())
    ## get the logfile location
    log_file = lib.my_globals.get_log_file()
    if log_file:
        lines.append("Logfile: %s\n" % log_file)
    ## get the full command with resolved paths
    full_command = lib.my_globals.get_full_command()
    if full_command:
        lines.append("Command: %s\n" % full_command)
    return lines


def write_metadata(dest, dest_host, started_on, completed_on=None):
    """
    Write installation metadata to the destination directory.

    This is called twice for each site:
      * Once at the very beginning of the installation, before anything is
        copied in (``completed_on`` is None). This establishes the deletion
        policy up front so that an interrupted install can still be deleted.
      * Once after the installation finishes successfully (``completed_on`` is
        set) to record the completion time.

    Args:
        dest:         The destination directory path
        dest_host:    The host with write access to /tools_vendor (from siteHash)
        started_on:   The datetime the install started. The same value is passed
                      on both calls so the "Install started on" timestamp is
                      preserved across the initial and completion writes.
        completed_on: The datetime the install completed, or None for the
                      initial write.
    """
    pid = os.getpid()
    user = getpass.getuser()
    metadata = ".cadinstall.metadata"
    tmp_metadata = "/tmp/%s.%s.%d" % (metadata, user, pid)
    dest_metadata = dest + "/" + metadata

    phase = "completion" if completed_on is not None else "initial"

    # Always create the temp file locally
    f = open(tmp_metadata, 'w')
    for line in _build_metadata_lines(user, started_on, completed_on):
        f.write(line)
    f.close()

    os.system("/usr/bin/chmod 755 %s" % (tmp_metadata))

    # Make sure the destination directory exists. On the initial write nothing
    # has been copied in yet, so the directory will not exist. rsync of a single
    # file will not create the parent directory for us.
    if check_same_host(dest_host) == 0:
        mkdir_command = "%s -p %s" % (mkdir, dest)
    else:
        mkdir_command = "/usr/bin/ssh %s %s -p %s" % (dest_host, mkdir, dest)
    run_command(mkdir_command)

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
        logger.info("Wrote %s metadata file: %s on %s" % (phase, dest_metadata, dest_host))
    else:
        logger.warning("Failed to write %s metadata file: %s on %s" % (phase, dest_metadata, dest_host))

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
    install_started_on = None
    install_completed_on = None
    legacy_installed_on = None
    for line in metadata_contents.splitlines():
        if line.startswith("Installed by:"):
            installed_by = line.split(":", 1)[1].strip()
        elif line.startswith("Install started on:"):
            install_started_on = line.split(":", 1)[1].strip()
        elif line.startswith("Install completed on:"):
            install_completed_on = line.split(":", 1)[1].strip()
        elif line.startswith("Installed on:"):
            # Legacy metadata format (pre HWINFRA-938) used a single
            # "Installed on" timestamp. Keep reading it as a fallback so that
            # tools installed with the old format can still be deleted.
            legacy_installed_on = line.split(":", 1)[1].strip()

    # Deletion policy timestamp: prefer the completion time (a fully completed
    # install). If only the start time exists the install was interrupted, so
    # base the policy on when it started. Fall back to the legacy timestamp for
    # metadata written before this field was split.
    if install_completed_on:
        installed_on = install_completed_on
        install_time_label = "Install completed on"
    elif install_started_on:
        installed_on = install_started_on
        install_time_label = "Install started on"
    else:
        installed_on = legacy_installed_on
        install_time_label = "Installed on"

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

    install_time = _parse_metadata_time(installed_on)
    if install_time is None:
        logger.error("Could not parse installation timestamp: '%s'" % installed_on)
        logger.error("Deletion is not allowed.")
        sys.exit(1)

    from lib.tool_defs import delete_time_limit
    # Compare against "now" in the same awareness as the stored timestamp:
    # timezone-aware for current metadata, naive for legacy metadata.
    if install_time.tzinfo is not None:
        now = datetime.now(install_time.tzinfo)
    else:
        now = datetime.now()
    elapsed = now - install_time
    elapsed_minutes = elapsed.total_seconds() / 60.0

    if elapsed_minutes > delete_time_limit:
        now_display = _format_metadata_time(now) if now.tzinfo is not None else str(now)
        logger.error("Deletion time window has expired.")
        logger.error("%-19s: %s" % (install_time_label, installed_on))
        logger.error("Current time       : %s" % now_display)
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

def check_install_permissions(dest, dest_host):
    """
    Check if we have write permissions to create the tool installation directory.
    Walks up from the target path until an existing parent is found, then checks
    that it is writable.

    Args:
        dest: The full destination path (e.g. /tools_vendor/FOSS/verilator/5.046)
        dest_host: The host with write access to /tools_vendor (from siteHash)

    Returns:
        True if permissions are OK, False otherwise.
    """
    logger.info("Checking install directory permissions for %s on %s ..." % (dest, dest_host))

    path_to_check = dest
    while path_to_check != "/" and path_to_check != "":
        if check_same_host(dest_host) == 0:
            exists_command = "/bin/test -d %s" % path_to_check
        else:
            exists_command = "/usr/bin/ssh %s /bin/test -d %s" % (dest_host, path_to_check)

        exists_status, _ = run_command_with_output(exists_command, force_run=True)

        if exists_status == 0:
            if check_same_host(dest_host) == 0:
                write_command = "/bin/test -w %s" % path_to_check
            else:
                write_command = "/usr/bin/ssh %s /bin/test -w %s" % (dest_host, path_to_check)

            write_status, _ = run_command_with_output(write_command, force_run=True)

            if write_status != 0:
                logger.error("No write permission to create install directory. Cannot write to: %s on %s" % (path_to_check, dest_host))
                return False
            else:
                logger.info("Install directory permissions check passed - can write to: %s on %s" % (path_to_check, dest_host))
                return True

        path_to_check = os.path.dirname(path_to_check)

    logger.error("Could not find any existing parent directory for install path: %s on %s" % (dest, dest_host))
    return False

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
    
    # Build the full path that needs to be created
    vendor_tool_path = "%s/%s/%s" % (module_path, vendor, tool)
    
    # Find the first existing parent directory by walking up the path
    path_to_check = vendor_tool_path
    while path_to_check != "/" and path_to_check != "":
        # Check if this directory exists
        if check_same_host(dest_host) == 0:
            exists_command = "/bin/test -d %s" % path_to_check
        else:
            exists_command = "/usr/bin/ssh %s /bin/test -d %s" % (dest_host, path_to_check)
        
        exists_status, _ = run_command_with_output(exists_command, force_run=True)
        
        if exists_status == 0:
            # This directory exists, check if it's writable
            if check_same_host(dest_host) == 0:
                write_command = "/bin/test -w %s" % path_to_check
            else:
                write_command = "/usr/bin/ssh %s /bin/test -w %s" % (dest_host, path_to_check)
            
            write_status, _ = run_command_with_output(write_command, force_run=True)
            
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

