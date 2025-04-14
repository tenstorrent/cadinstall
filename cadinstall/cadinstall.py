#!/usr/bin/python3
# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

import os
import sys
import argparse
import pwd
import grp
import re

sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/..')
import cadinstall.log as log
import cadinstall.my_globals as my_globals
from cadinstall.tool_defs import *
from cadinstall.utils import *
from cadinstall.install import *

## define the full path to this script
script = os.path.realpath(__file__)

## define the full path to this script along with all of the arguments used in it's invocation
full_command = ' '.join(sys.argv)

log_file = '/tmp/cadinstall.' + user + '.log'
logger = log.setup_custom_logger('cadinstall', log_file)

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
install_parser.add_argument('--addlink', dest="link", required=False, help='The name of the symlink to create that will point to the new version created. Typically used for creating the \"latest\" symlink')
install_parser.add_argument('--sites', type=str, dest="sites", default="", required=False, help='The sites to install the tool to. Valid values: aus, yyz')
install_parser.add_argument('--group', dest="group", default=cadtools_group, help='The group to own the destination directory')

def main():
    args = parser.parse_args()
    install_args = install_parser.parse_args()

    if install_args.sites:
        sitesList = args.sites.split(",")
    else:
        sitesList = []

        ## Get the domain of the current machine
        command = "/usr/bin/dnsdomainname"
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        domain = process.stdout.read().decode('utf-8').rstrip().split('.')[0]
        domain = domain[:3]

        for site in siteHash:
            ## skipping the local site because i want to force it to be first in the list
            if site != domain:
                sitesList.append(site)

        if domain in siteHash:
            ## now make sure to push the local site to the front of the list. this ensures that the localsite
            ## gets updated first which is probably what the user wants
            sitesList.insert(0, domain)

    # Set up the logging level
    if args.verbose:
        logger.setLevel(logging.INFO)
        my_globals.set_verbose(True)
    if args.vv:
        my_globals.set_vv(True)
        logger.setLevel(logging.DEBUG)
    if args.quiet:
        my_globals.set_quiet(True)
        my_globals.set_verbose(False)
        my_globals.set_vv(False)
        logger.setLevel(logging.ERROR)

    # Set up the pretend switch
    if args.pretend:
        my_globals.set_pretend(True)
    else:
        my_globals.set_pretend(False)

    if args.force:
        my_globals.set_force(True)

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

            if args.link:
                create_link(dest, vendor, tool, version, args.link, dest_host)

            ## Now that one site is done, change the source to the installed site so that we are ensuring all sites are equivalent
            ## But don't do this if the final_dest is on tmp because that won't be accessible
            if not re.search("^/tmp", final_dest):
                src = final_dest

    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()


