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

## define the full path to this script
script = os.path.realpath(__file__)

## define the full path to this script along with all of the arguments used in it's invocation
full_command = ' '.join(sys.argv)

log_file = '/tmp/cadinstall.' + user + '.log'
logger = lib.log.setup_custom_logger('cadinstall', log_file)

# Set up the argument parser
parser = argparse.ArgumentParser(
    description='Install tools from vendors across multiple sites',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
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
)
parser.add_argument('--verbose', '-v', action='count', default=0, help='Print all output to the console and the log file (use -vv or --vv for extra verbose)')
parser.add_argument('--vv', action='store_true', help='Print all output to the console and the log file, but also print out the commands that are being run')
parser.add_argument('--quiet', '-q', action='store_true', help='Suppress all output to the console except for errors. Print all output to the log file')
parser.add_argument('--pretend', '-p', action='store_true', help='Print out the command that would be run, but do not actually run the command')
parser.add_argument('--force', '-f', action='store_true', help='Forces the installation despite any warnings/errors such as the destination already existing')
subparsers = parser.add_subparsers(dest='subcommand', help='Available subcommands')
install_parser = subparsers.add_parser('install', help='Install a tool from a vendor')
install_parser.add_argument('--vendor', dest="vendor", required=True, help='The vendor of the tool (e.g., synopsys, cadence)')
install_parser.add_argument('--tool', '-t', dest="tool", required=True, help='The tool to install (e.g., vcs, icc2)')
install_parser.add_argument('--version', '-ver', dest="version", required=True, help='The version of the tool to install (e.g., 2023.12)')
install_parser.add_argument('--src', dest="src", required=True, help='The source directory of the tool installation files')
install_parser.add_argument('--addlink', dest="link", required=False, help='The name of the symlink to create that will point to the new version created. Typically used for creating the \"latest\" symlink')
install_parser.add_argument('--sites', type=str, required=False, help='Comma-separated list of sites to install the tool to. Valid values: aus, yyz. If not specified, installs to all sites')
install_parser.add_argument('--group', dest="group", default=cadtools_group, help='The group to own the destination directory')
install_parser.add_argument('--skip-modules', dest="skip_modules", action='store_true', help='Skip module file installation (useful when permissions are insufficient)')
args = parser.parse_args()

# Check if no subcommand was provided
if not args.subcommand:
    print("Error: No subcommand provided.")
    print("\nAvailable subcommands:")
    print("  install    Install a tool from a vendor")
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

        for site in sitesList:
            dest_host = siteHash[site]
            final_dest = "%s/%s/%s/%s" % (dest, vendor, tool, version)
            
            # Check module permissions BEFORE starting installation to prevent incomplete installations
            if not (hasattr(args, 'skip_modules') and args.skip_modules):
                if not check_module_permissions(vendor, tool, dest_host):
                    logger.error("Insufficient permissions for module file installation on %s." % site)
                    logger.error("Use --skip-modules flag to skip module installation and continue.")
                    sys.exit(1)
            
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

    else:
        logger.error("Unknown subcommand: %s" % args.subcommand)
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()










