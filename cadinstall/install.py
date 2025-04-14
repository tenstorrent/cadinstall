# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

from cadinstall.utils import *
from cadinstall.tool_defs import *
import cadinstall.my_globals
import getpass
import socket
from datetime import datetime


import logging
logger = logging.getLogger('cadinstall')

def install_tool(vendor, tool, version, src, group, dest_host, dest):
    check_src(src)

    if check_dest(dest, dest_host):
        if my_globals.get_force():
            logger.warn("Proceeding anyways because the '--force' switch was thrown")
        else:
            sys.exit(1)
    
    logger.info("Copying %s/%s/%s to %s ..." % (vendor,tool,version,dest_host))

    command = "%s %s --groupmap=\"*:%s\" --rsync-path=\'%s -p %s && %s\' %s/ %s:%s/" % (rsync, rsync_options, cadtools_group, mkdir, dest, rsync, src, dest_host, dest)
    status = run_command(command, my_globals.pretend)

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
    status = run_command(command, my_globals.pretend)

    os.remove(tmp_metadata)

def create_link(dest, vendor, tool, version, link, dest_host):
    logger.info("Creating a symlink called %s/%s/%s/%s that points to ./%s ..." % (dest,vendor,tool,link,version))

    command = "/usr/bin/ssh %s /usr/bin/ln -sfT ./%s %s/%s/%s/%s" % (dest_host, version,dest,vendor,tool,link)
    status = run_command(command, my_globals.pretend)

    return(status)


