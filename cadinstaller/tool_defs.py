# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

import getpass
import socket
import os

global vendor
global tool
global version
global src
global sitesList
global group

#########################################
##                                     ##
## Your installation-specific settings ##
##                                     ##
#########################################
## This is the basepath where all tool installations will live
dest = '/tools_vendor'
## This is the account that will own all tool installations
cadtools_user = 'cadtools'
## This is the default unix group that will protect all tool installations
cadtools_group = 'vendor_tools'
## This is the default unix permission set that will protect all tool installations
dest_mode = 2755

## Required system command paths
rsync = '/usr/bin/rsync'
mkdir = '/usr/bin/mkdir'
curl = '/usr/bin/curl'

## Each site where tools are to be installed at
siteHash = {
    'aus': 'rv-misc-01.aus2.tenstorrent.com',
    'yyz': 'soc-l-01.yyz2.tenstorrent.com'
}

## Generic global variables, probably don't need to change any of these
user = getpass.getuser()
host = socket.getfqdn()

rsync_exclude_file = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + '/../etc/rsync_exclude_list.txt')
rsync_options = "-av --chmod=u+rwx,g+rx,o=rx --exclude-from=%s" % (rsync_exclude_file)


