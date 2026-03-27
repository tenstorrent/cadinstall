#!/usr/bin/python3
# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

import os
import sys
import argparse
import pwd
import grp
import re
import subprocess

sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/..')
import lib.log
import lib.my_globals
from lib.tool_defs import *
from lib.utils import *
from lib.install import *
from lib.executor import initialize_executor

## define the full path to this script
script = os.path.realpath(__file__)

## define the full path to this script along with all of the arguments used in it's invocation
full_command = ' '.join(sys.argv)

## create a version of the command with all paths resolved to their real paths
def resolve_command_paths(argv):
    """
    Resolve all file/directory paths in the command line to their real paths.
    This converts symlinks to actual paths, showing real versions instead of 'latest' links.
    """
    resolved_args = []
    for i, arg in enumerate(argv):
        # Check if this looks like a file or directory path
        if os.path.exists(arg):
            # Resolve to real path
            resolved_args.append(os.path.realpath(arg))
        elif arg.startswith('--src='):
            # Handle --src=PATH format
            prefix = '--src='
            path = arg[len(prefix):]
            if os.path.exists(path):
                resolved_args.append(prefix + os.path.realpath(path))
            else:
                resolved_args.append(arg)
        elif i > 0 and argv[i-1] == '--src':
            # Handle --src PATH format (path argument after --src flag)
            if os.path.exists(arg):
                resolved_args.append(os.path.realpath(arg))
            else:
                resolved_args.append(arg)
        else:
            resolved_args.append(arg)
    return ' '.join(resolved_args)

resolved_command = resolve_command_paths(sys.argv)
lib.my_globals.set_full_command(resolved_command)

log_file = '/tmp/cadinstall.%s.%d.log' % (user, os.getpid())
lib.my_globals.set_log_file(log_file)
logger = lib.log.setup_custom_logger('cadinstall', log_file)

# Set up the argument parser
epilog_text = """
Examples:
  # Install a tool to all sites (includes module files)
  cadinstall.py install --vendor synopsys --tool vcs --version 2023.12 --src /tmp/vcs_install

  # Install with a specific symlink
  cadinstall.py install --vendor synopsys --tool vcs --version 2023.12 --src /tmp/vcs_install --addlink latest

  # Install to specific sites only
  cadinstall.py install --vendor synopsys --tool vcs --version 2023.12 --src /tmp/vcs_install --sites aus,yyz

  # Skip module file installation (useful when permissions are insufficient)
  cadinstall.py install --vendor synopsys --tool vcs --version 2023.12 --src /tmp/vcs_install --skip-modules

  # Dry run (pretend mode)
  cadinstall.py --pretend install --vendor synopsys --tool vcs --version 2023.12 --src /tmp/vcs_install
"""
if 'addlink' not in disabled_subcommands:
    epilog_text += """
  # Create or update a symlink for a previously installed tool version
  cadinstall.py addlink --vendor anthropic --tool claude-code --version 2.1.71 --link latest

  # Create a symlink on a specific site only
  cadinstall.py addlink --vendor synopsys --tool vcs --version 2023.12 --link latest --sites yyz
"""
if 'delete' not in disabled_subcommands:
    epilog_text += """
  # Delete a specific tool version (must be run by the installing user within the allowed time window)
  cadinstall.py delete --vendor synopsys --tool vcs --version 2023.12

  # Delete from a specific site only
  cadinstall.py delete --vendor synopsys --tool vcs --version 2023.12 --sites yyz

  # Dry run of a delete (check if all conditions are met without actually deleting)
  cadinstall.py --pretend delete --vendor synopsys --tool vcs --version 2023.12
"""
parser = argparse.ArgumentParser(
    description='Install tools from vendors across multiple sites',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=epilog_text
)
parser.add_argument('--verbose', '-v', action='count', default=0, help='Print all output to the console and the log file (use -vv or --vv for extra verbose)')
parser.add_argument('--vv', action='store_true', help='Print all output to the console and the log file, but also print out the commands that are being run')
parser.add_argument('--quiet', '-q', action='store_true', help='Suppress all output to the console except for errors. Print all output to the log file')
parser.add_argument('--pretend', '-p', action='store_true', help='Print out the command that would be run, but do not actually run the command')
parser.add_argument('--force', '-f', action='store_true', help='Forces the installation despite any warnings/errors such as the destination already existing')
subparsers = parser.add_subparsers(dest='subcommand', help='Available subcommands')
install_parser = subparsers.add_parser('install', help='Install a tool from a vendor')
install_required = install_parser.add_argument_group('required arguments')
install_required.add_argument('--vendor', dest="vendor", required=True, help='The vendor of the tool (e.g., synopsys, cadence)')
install_required.add_argument('--tool', '-t', dest="tool", required=True, help='The tool to install (e.g., vcs, icc2)')
install_required.add_argument('--version', '-ver', dest="version", required=True, help='The version of the tool to install (e.g., 2023.12)')
install_required.add_argument('--src', dest="src", required=True, help='The source directory of the tool installation files')
install_parser.add_argument('--addlink', dest="link", required=False, help='The name of the symlink to create that will point to the new version created. Typically used for creating the \"latest\" symlink')
install_parser.add_argument('--sites', type=str, required=False, help='Comma-separated list of sites to install the tool to. Valid values: aus, yyz. If not specified, installs to all sites')
install_parser.add_argument('--group', dest="group", default=cadtools_group, help='The group to own the destination directory')
install_parser.add_argument('--skip-modules', dest="skip_modules", action='store_true', help='Skip module file installation (useful when permissions are insufficient)')

# --- addlink subcommand (gated by disabled_subcommands in tool_defs.py) ---
if 'addlink' not in disabled_subcommands:
    addlink_parser = subparsers.add_parser('addlink', help='Create or update a symlink for a previously installed vendor/tool/version')
    addlink_required = addlink_parser.add_argument_group('required arguments')
    addlink_required.add_argument('--vendor', dest="vendor", required=True, help='The vendor of the tool (e.g., synopsys, cadence)')
    addlink_required.add_argument('--tool', '-t', dest="tool", required=True, help='The tool (e.g., vcs, icc2)')
    addlink_required.add_argument('--version', '-ver', dest="version", required=True, help='The version to point the symlink to (e.g., 2023.12). Must be an existing version in the tool directory')
    addlink_required.add_argument('--link', '-l', dest="link", required=True, help='The name of the symlink to create (e.g., latest)')
    addlink_parser.add_argument('--sites', type=str, required=False, help='Comma-separated list of sites. Valid values: aus, yyz. If not specified, applies to all sites')

# --- delete subcommand (gated by disabled_subcommands in tool_defs.py) ---
if 'delete' not in disabled_subcommands:
    delete_parser = subparsers.add_parser('delete', help='Delete a previously installed vendor/tool/version')
    delete_required = delete_parser.add_argument_group('required arguments')
    delete_required.add_argument('--vendor', dest="vendor", required=True, help='The vendor of the tool (e.g., synopsys, cadence)')
    delete_required.add_argument('--tool', '-t', dest="tool", required=True, help='The tool to delete (e.g., vcs, icc2)')
    delete_required.add_argument('--version', '-ver', dest="version", required=True, help='The version of the tool to delete (e.g., 2023.12)')
    delete_parser.add_argument('--sites', type=str, required=False, help='Comma-separated list of sites to delete the tool from. Valid values: aus, yyz. If not specified, deletes from all sites')

args = parser.parse_args()

# Check if no subcommand was provided
if not args.subcommand:
    print("Error: No subcommand provided.")
    print("\nAvailable subcommands:")
    print("  install    Install a tool from a vendor")
    if 'addlink' not in disabled_subcommands:
        print("  addlink    Create or update a symlink for a previously installed version")
    if 'delete' not in disabled_subcommands:
        print("  delete     Delete a previously installed vendor/tool/version")
    print("\nFor detailed help on a specific subcommand, use:")
    print("  cadinstall.py <subcommand> --help")
    print("\nFor general help, use:")
    print("  cadinstall.py --help")
    parser.print_help()
    sys.exit(1)

# Set up the logging level
if args.verbose >= 1:
    logger.setLevel(logging.INFO)
    lib.my_globals.set_verbose(True)
if args.vv or args.verbose >= 2:
    lib.my_globals.set_vv(True)
    logger.setLevel(logging.DEBUG)
if args.quiet:
    lib.my_globals.set_quiet(True)
    lib.my_globals.set_verbose(False)
    lib.my_globals.set_vv(False)
    logger.setLevel(logging.ERROR)

# Set up the pretend switch
if args.pretend:
    lib.my_globals.set_pretend(True)
else:
    lib.my_globals.set_pretend(False)

if args.force:
    lib.my_globals.set_force(True)

# Initialize sitesList - this will be populated in the main() function based on subcommand
sitesList = []

def main():
    global sitesList
    
    logger.info("User    : %s" % user)
    logger.info("Host    : %s" % host)
    logger.info("Cmdline : %s" % full_command)
    logger.info("Logfile : %s" % log_file)

    # Initialize the executor (check for setuid binary or listener)
    initialize_executor()

    if user == cadtools_user:
        logger.error("This command cannot be run directly by %s. Please rerun as another user.\n" %(cadtools_user))
        sys.exit(1)

    if args.subcommand == 'install':
        # Set up the global variables for the install subcommand
        vendor = args.vendor
        tool = args.tool
        version = args.version
        src = args.src
        
        # Handle sites argument - this is now safe since we know we're in the install subcommand
        if hasattr(args, 'sites') and args.sites:
            sitesList = args.sites.split(",")
            sites = args.sites
            
            # Validate that all specified sites exist in siteHash
            invalid_sites = [site for site in sitesList if site not in siteHash]
            if invalid_sites:
                valid_sites = ', '.join(sorted(siteHash.keys()))
                logger.error("Invalid site(s) specified: %s" % ', '.join(invalid_sites))
                logger.error("Valid sites are: %s" % valid_sites)
                sys.exit(1)
        else:
            sites = 'all'
            # Get the domain of the current machine
            command = "/usr/bin/dnsdomainname"
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            domain = process.stdout.read().decode('utf-8').rstrip().split('.')[0]
            domain = domain[:3]

            for site in siteHash:
                # skipping the local site because i want to force it to be first in the list
                if site != domain:
                    sitesList.append(site)
            
            if domain in siteHash:
                # now make sure to push the local site to the front of the list. this ensures that the localsite
                # gets updated first which is probably what the user wants
                sitesList.insert(0, domain)
        
        if hasattr(args, 'group') and args.group:
            group = args.group
        else:
            group = cadtools_group

        # Validate required arguments
        if not vendor or not tool or not version or not src:
            logger.error("Missing required arguments for install subcommand")
            install_parser.print_help()
            sys.exit(1)

        # Perform disk space precheck before starting installation
        from lib.utils import check_disk_space_precheck
        success, sites_with_space, sites_without_space = check_disk_space_precheck(
            src, sitesList, vendor, tool, version, dest)
        
        if not success:
            logger.error("Disk space precheck failed!")
            if sites_with_space and sites_without_space:
                # Some sites have space, some don't - suggest using --sites switch
                logger.error("Insufficient disk space on sites: %s" % ', '.join(sites_without_space))
                logger.error("Sites with sufficient space: %s" % ', '.join(sites_with_space))
                logger.error("")
                logger.error("To install only to sites with sufficient space, use:")
                logger.error("  --sites %s" % ','.join(sites_with_space))
                sys.exit(1)
            elif sites_without_space:
                # No sites have sufficient space
                logger.error("Insufficient disk space on all target sites: %s" % ', '.join(sites_without_space))
                logger.error("Please free up disk space or choose a different installation location.")
                sys.exit(1)
            else:
                # No sites in either list - likely an error checking source directory or other critical failure
                logger.error("Critical error during disk space precheck. Cannot proceed.")
                sys.exit(1)
        else:
            logger.info("Disk space precheck passed for all sites: %s" % ', '.join(sites_with_space))

        # Pre-validate ALL sites before starting any installation.
        # This prevents partial installations where one site succeeds and another fails.
        final_dest = "%s/%s/%s/%s" % (dest, vendor, tool, version)
        for site in sitesList:
            dest_host = siteHash[site]
            other_sites = [s for s in sitesList if s != site]

            # Check that the destination does not already exist
            if check_dest(final_dest, dest_host):
                logger.error("Aborting installation to ALL sites. No changes have been made.")
                if other_sites:
                    logger.error("To install only to the other site(s), rerun with: --sites %s" % ','.join(other_sites))
                sys.exit(1)

            if not check_install_permissions(final_dest, dest_host):
                logger.error("Insufficient permissions to install %s on %s." % (final_dest, site))
                logger.error("Aborting installation to ALL sites. No changes have been made.")
                if other_sites:
                    logger.error("To install only to the other site(s), rerun with: --sites %s" % ','.join(other_sites))
                sys.exit(1)

            if not (hasattr(args, 'skip_modules') and args.skip_modules):
                if not check_module_permissions(vendor, tool, dest_host):
                    logger.error("Insufficient permissions for module file installation on %s." % site)
                    logger.error("Aborting installation to ALL sites. No changes have been made.")
                    if other_sites:
                        logger.error("To install only to the other site(s), rerun with: --sites %s" % ','.join(other_sites))
                    logger.error("Or use --skip-modules flag to skip module installation and continue.")
                    sys.exit(1)

        logger.info("Prechecks passed for all sites: %s" % ', '.join(sitesList))

        if lib.my_globals.get_pretend():
            logger.info("")
            logger.info("="*80)
            logger.info("PRETEND MODE: All prechecks passed. No files were copied or modified.")
            logger.info("To perform the actual installation, rerun without the '--pretend' switch.")
            logger.info("="*80)
        else:
            for site in sitesList:
                dest_host = siteHash[site]
                
                logger.info("Installing %s to %s ..." %(final_dest,site))
                install_tool(vendor, tool, version, src, group, dest_host, final_dest)

                if hasattr(args, 'link') and args.link:
                    create_link(dest, vendor, tool, version, args.link, dest_host)

                # Install module files unless --skip-modules was specified
                if not (hasattr(args, 'skip_modules') and args.skip_modules):
                    module_status = install_module_files(vendor, tool, version, dest_host)
                    if module_status != 0:
                        logger.error("Module file installation failed for %s. Use --skip-modules to bypass." % site)
                        sys.exit(1)
                else:
                    logger.info("Skipping module file installation (--skip-modules specified)")

                # Now that one site is done, change the source to the installed site so that we are ensuring all sites are equivalent
                # But don't do this if the final_dest is on tmp because that won't be accessible
                if not re.search("^/tmp", final_dest):
                    src = final_dest
            
            # Check if installation was only to yyz2-nfspublish (Pure filesystem replication)
            unique_hosts = set([siteHash[site] for site in sitesList])
            if len(unique_hosts) == 1 and 'yyz2-nfspublish.yyz2.tenstorrent.com' in unique_hosts:
                logger.info("")
                logger.info("="*80)
                logger.info("IMPORTANT: Installation completed to yyz2-nfspublish.yyz2.tenstorrent.com")
                logger.info("This installation relies on Pure filesystem replication to propagate to other sites.")
                logger.info("Replication can take up to 15 minutes before the installation is visible at other sites.")
                logger.info("")
                logger.info("If you are running from a non-YYZ site (e.g., AUS), please allow time for")
                logger.info("replication before expecting the installation to be available locally.")
                logger.info("="*80)

    elif args.subcommand == 'addlink':
        if 'addlink' in disabled_subcommands:
            logger.error("The 'addlink' subcommand is currently disabled.")
            sys.exit(1)

        vendor = args.vendor
        tool = args.tool
        version = args.version
        link = args.link

        # Validate that version is a plain directory name — reject anything that
        # looks like an absolute or relative path to prevent linking outside the
        # tool directory tree.
        path_component_re = re.compile(r'^(?!\.+$)[A-Za-z0-9][A-Za-z0-9._-]*$')
        for label, value in [('vendor', vendor), ('tool', tool), ('version', version), ('link', link)]:
            if not value or not path_component_re.match(value):
                logger.error("Invalid %s value: '%s'. Must be a plain directory name "
                             "(no slashes, no dots-only, no whitespace)." % (label, value))
                sys.exit(1)

        # Handle sites argument
        if hasattr(args, 'sites') and args.sites:
            sitesList = args.sites.split(",")

            invalid_sites = [site for site in sitesList if site not in siteHash]
            if invalid_sites:
                valid_sites = ', '.join(sorted(siteHash.keys()))
                logger.error("Invalid site(s) specified: %s" % ', '.join(invalid_sites))
                logger.error("Valid sites are: %s" % valid_sites)
                sys.exit(1)
        else:
            command = "/usr/bin/dnsdomainname"
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            domain = process.stdout.read().decode('utf-8').rstrip().split('.')[0]
            domain = domain[:3]

            for site in siteHash:
                if site != domain:
                    sitesList.append(site)

            if domain in siteHash:
                sitesList.insert(0, domain)

        if link == version:
            logger.error("The --link name '%s' is the same as --version. "
                         "The symlink cannot point to itself." % link)
            sys.exit(1)

        for site in sitesList:
            dest_host = siteHash[site]
            version_dir = "%s/%s/%s/%s" % (dest, vendor, tool, version)
            link_path = "%s/%s/%s/%s" % (dest, vendor, tool, link)
            is_local = (check_same_host(dest_host) == 0)

            if lib.my_globals.get_pretend():
                logger.info("Pretend mode: would verify version directory exists: %s on %s" % (version_dir, dest_host))
                logger.info("Pretend mode: would verify link name is not an existing directory: %s on %s" % (link_path, dest_host))
            else:
                # Verify the version directory exists on the target host
                if is_local:
                    test_command = "/bin/test -d %s" % version_dir
                else:
                    test_command = "/usr/bin/ssh %s /bin/test -d %s" % (dest_host, version_dir)

                test_status = run_command(test_command)
                if test_status != 0:
                    logger.error("Version directory does not exist: %s on %s" % (version_dir, dest_host))
                    logger.error("The --version must refer to an already-installed version.")
                    sys.exit(1)

                # Verify the link name does not collide with an existing real
                # directory (an existing symlink is fine — we'll overwrite it).
                # "test -d X && ! test -L X" is true only for real directories.
                if is_local:
                    collision_command = "/bin/test -d %s && ! /bin/test -L %s" % (link_path, link_path)
                else:
                    collision_command = "/usr/bin/ssh %s '/bin/test -d %s && ! /bin/test -L %s'" % (dest_host, link_path, link_path)

                collision_status = run_command(collision_command)
                if collision_status == 0:
                    logger.error("The link name '%s' conflicts with an existing installed version directory: %s on %s" % (link, link_path, dest_host))
                    logger.error("A symlink cannot overwrite a real installation directory.")
                    sys.exit(1)

            # Check if the link already exists as a symlink so we can report
            # whether this is a create or an update (and from which version).
            old_target = None
            if is_local:
                readlink_command = "/bin/readlink %s" % link_path
            else:
                readlink_command = "/usr/bin/ssh %s /bin/readlink %s" % (dest_host, link_path)
            rl_status, rl_output = run_command_with_output(readlink_command, force_run=True)
            if rl_status == 0 and rl_output.strip():
                old_target = rl_output.strip().lstrip('./')

            if old_target and old_target != version:
                logger.info("Updating symlink '%s' from version '%s' to '%s' in %s/%s/%s on %s ..." % (link, old_target, version, dest, vendor, tool, site))
            elif old_target and old_target == version:
                logger.info("Symlink '%s' already points to '%s' in %s/%s/%s on %s, re-creating ..." % (link, version, dest, vendor, tool, site))
            else:
                logger.info("Creating symlink '%s' -> '%s' in %s/%s/%s on %s ..." % (link, version, dest, vendor, tool, site))

            status = create_link(dest, vendor, tool, version, link, dest_host)
            if status != 0:
                logger.error("Failed to create symlink on %s" % site)
                sys.exit(1)

    elif args.subcommand == 'delete':
        if 'delete' in disabled_subcommands:
            logger.error("The 'delete' subcommand is currently disabled.")
            sys.exit(1)

        vendor = args.vendor
        tool = args.tool
        version = args.version

        # Handle sites argument
        if hasattr(args, 'sites') and args.sites:
            sitesList = args.sites.split(",")

            # Validate that all specified sites exist in siteHash
            invalid_sites = [site for site in sitesList if site not in siteHash]
            if invalid_sites:
                valid_sites = ', '.join(sorted(siteHash.keys()))
                logger.error("Invalid site(s) specified: %s" % ', '.join(invalid_sites))
                logger.error("Valid sites are: %s" % valid_sites)
                sys.exit(1)
        else:
            # Get the domain of the current machine
            command = "/usr/bin/dnsdomainname"
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            domain = process.stdout.read().decode('utf-8').rstrip().split('.')[0]
            domain = domain[:3]

            for site in siteHash:
                if site != domain:
                    sitesList.append(site)

            if domain in siteHash:
                sitesList.insert(0, domain)

        for site in sitesList:
            dest_host = siteHash[site]
            final_dest = "%s/%s/%s/%s" % (dest, vendor, tool, version)

            logger.info("Deleting %s from %s ..." % (final_dest, site))
            delete_tool(vendor, tool, version, dest_host, final_dest)

    else:
        logger.error("Unknown subcommand: %s" % args.subcommand)
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()










