from lib.utils import *
from lib.tool_defs import *
import lib.my_globals

import logging
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

    if check_domain(dest_host) == 0:
        write_metadata(dest)

    return(status)

def write_metadata(dest):
    metadata = dest + "/.cadinstall.metadata"
    f = open(metadata, 'w')
    f.write("Installed by: %s\n" % get_user())
    f.write("Installed on: %s\n" % get_date())
    ## get fully qualified hostname
    f.write("Installed from: %s\n" % get_host())
    f.write("Installation logfile: %s\n" % lib.my_globals.logfile)
    f.close()



