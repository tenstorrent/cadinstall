import os
import sys
import subprocess
import logging
import lib.my_globals

logger = logging.getLogger('cadinstall')

def run_command(command, pretend=False):
    sudo = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + '/../bin/.sudo ')

    pretend = lib.my_globals.get_pretend()

    if pretend:
        logger.info("Because the '-p' switch was thrown, not actually running command: %s" % command)
    else:
        sudo_command = command
        ## Prefix every instance of '/usr/bin/mkdir' in sudo_command with sudo
        sudo_command = sudo_command.replace('/usr/bin/mkdir', sudo + '/usr/bin/mkdir')
        ## Prefix every instance of '/usr/bin/rsync' in sudo_command with sudo 
        sudo_command = sudo_command.replace('/usr/bin/rsync', sudo + '/usr/bin/rsync')

        if lib.my_globals.get_vv():
            logger.info("Running sudo_command: %s" % sudo_command)
        else:
            logger.info("Running command: %s" % command)

        from subprocess import PIPE, Popen
        #with Popen(command, shell=True, stdout=PIPE, stderr=PIPE, bufsize=1) as process:
        with Popen(sudo_command, shell=True, stdout=PIPE, stderr=PIPE, bufsize=1) as process:
            for line in process.stdout:
                logger.info(line.decode('utf-8').rstrip())
            for line in process.stderr:
                logger.error(line.decode('utf-8').rstrip())

            return_code = process.returncode
            logger.info("Return code: %s" % return_code)


def check_src(src):
    if not os.path.exists(src):
        logger.error("Source directory does not exist: %s" % src)
        sys.exit(1)

def check_dest(dest, host=None):
    exists = 0
    if host:
        logger.info("Checking %s for %s ..." % (host, dest))
        command = "ls -ltrd " + dest
        ssh = subprocess.Popen(["ssh", "%s" % host, command],
                       shell=False,
                       stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
        result = ssh.stdout.readlines()
        if result:
            logger.error("Destination directory already exists on %s : %s" % (host,dest))
            exists=1
            sys.exit(1)
    else:
        if os.path.exists(dest):
            logger.error("Destination directory already exists: %s" % dest)
            exists=1

    return(exists)
