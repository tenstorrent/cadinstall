#!/usr/bin/python3
## This script is used to install tools from vendors
## This script has a complete help menu for each of the supported subcommands
## This script has the following subcommands: install
## This script accepts a dry-run switchcalled "pretend" that will print out the command that would be run, but will not actually run the command
## The script accepts the following global switches that impatcs all print statements: verbose, vv, quiet
## The quiet switch will suppress all output to the console except for errors. It will still print out all output to the log file
## The verbose switch will print out all output to both the console and the log file
## The vv switch will print out all output to both the console and the logfile, but it will also print out the commands that are being run
## The install subcommand is used to install a tool and it takes the following switches: vendor, tool, version, src, sites, group
## The install subcommand will generate a command to rsync the src directory to a global installation area with the specified group
## If the script is NOT being run by the "cadtools" faceless account, it will make a call to a jenkins job to run the command that was generated
## If the script IS being run by the "cadtools" faceless account, it will run the command that was generated
## The script will exit with an error if the source directory does not exist, the destination directory already exists, or the destination directory does not exist
## The script will print out the subcommand help menu if no subcommand is provided
## The script will also exit with an error if an invalid subcommand is provided
## The script will print out the actions it is taking as it is running
## The script will also change the group of the destination directory to the specified group and change the permissions of the destination directory to allow both group and world read access

import os
import sys
import argparse
import pwd
import grp
import re

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
parser = argparse.ArgumentParser(description='Install tools from vendors')
parser.add_argument('--verbose', '-v', action='store_true', help='Print all output to the console and the log file')
parser.add_argument('--vv', action='store_true', help='Print all output to the console and the log file, but also print out the commands that are being run')
parser.add_argument('--quiet', '-q', action='store_true', help='Suppress all output to the console except for errors. Print all output to the log file')
parser.add_argument('--pretend', '-p', action='store_true', help='Print out the command that would be run, but do not actually run the command')
parser.add_argument('--force', '-f', action='store_true', help='Forces the installation despite any warnings/errors such as the destination already existing')
subparsers = parser.add_subparsers(dest='subcommand', help='Subcommands')
install_parser = subparsers.add_parser('install', help='Install a tool')
install_parser.add_argument('--vendor', '-v', dest="vendor", required=True, help='The vendor of the tool')
install_parser.add_argument('--tool', '-t', dest="tool", required=True, help='The tool to install')
install_parser.add_argument('--version', '-ver', dest="version", required=True, help='The version of the tool to install')
install_parser.add_argument('--src', dest="src", required=True, help='The source directory of the tool')
install_parser.add_argument('--sites', type=str, required=False, help='The sites to install the tool to. Valid values: aus, yyz')
install_parser.add_argument('--group', dest="group", default=cadtools_group, help='The group to own the destination directory')
args = parser.parse_args()

if args.sites:
    sitesList = args.sites.split(",")
else:
    sitesList = []
    for site in siteHash:
        sitesList.append(site)

# Set up the logging level
if args.verbose:
    logger.setLevel(logging.INFO)
    lib.my_globals.set_verbose(True)
if args.vv:
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

def main():
    ## show the help menu if no subcommand is provided
    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    logger.info("User    : %s" % user)
    logger.info("Host    : %s" % host)
    logger.info("Cmdline : %s" % full_command)
    logger.info("Logfile : %s" % log_file)

    # Set up the global variables for the install subcommand
    vendor = args.vendor
    tool = args.tool
    version = args.version
    src = args.src
    if args.sites:
        sites = args.sites
    else:
        sites = 'all'
    if args.group:
        group = args.group
    else:
        group = cadtools_group

    if user == cadtools_user:
        logger.error("This command cannot be run directly by %s. Please rerun as another user.\n" %(cadtools_user))
        sys.exit(1)

    if args.subcommand == 'install':
        for site in sitesList:
            dest_host = siteHash[site]
            final_dest = "%s/%s/%s/%s" % (dest, vendor, tool, version)
            logger.info("Installing %s to %s ..." %(final_dest,site))
            install_tool(vendor, tool, version, src, group, dest_host, final_dest)

            ## Now that one site is done, change the source to the installed site so that we are ensuring all sites are equivalent
            ## But don't do this if the final_dest is on tmp because that won't be accessible
            if not re.search("^/tmp", final_dest):
                src = final_dest

    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()










