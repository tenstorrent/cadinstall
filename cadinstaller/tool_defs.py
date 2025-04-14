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

user = getpass.getuser()
host = socket.getfqdn()
cadtools_user = 'cadtools'
cadtools_group = 'vendor_tools'

#dest = '/tmp/tools_vendor'
dest = '/tools_vendor'
dest_group = 'cadtools'
dest_mode = 2755

rsync = '/usr/bin/rsync'
mkdir = '/usr/bin/mkdir'
curl = '/usr/bin/curl'
rsync_exclude_file = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + '/../etc/rsync_exclude_list.txt')
rsync_options = "-av --chmod=u+rwx,g+rx,o=rx --exclude-from=%s" % (rsync_exclude_file)

# Set up the global variables for the jenkins job
curl_cmd = curl + ' -X POST -L'
jenkins_user = "bswan:11ce74b6c978b1484607c6c9168e085b44"
jenkins_url = 'http://aus-rv-l-7:8081'

## define a hash for machines per site
siteHash = {
    'aus': 'rv-misc-01.aus2.tenstorrent.com',
    'yyz': 'soc-l-01.yyz2.tenstorrent.com'
}


