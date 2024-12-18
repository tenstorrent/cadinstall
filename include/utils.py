# utils.py
# make this file importable for other python scripts

import os
import sys
import argparse
import logging
import subprocess
import getpass
import pwd
import grp
import shlex
import inspect

# Set up the global variable


def read_file(file_path):
    """Read the contents of a file and return as a string."""
    with open(file_path, 'r') as file:
        return file.read()

def write_file(file_path, content):
    """Write the given content to a file."""
    with open(file_path, 'w') as file:
        file.write(content)

def append_to_file(file_path, content):
    """Append the given content to a file."""
    with open(file_path, 'a') as file:
        file.write(content)

def list_files(directory):
    """List all files in the given directory."""
    import os
    return os.listdir(directory)

def file_exists(file_path):
    """Check if a file exists."""
    import os
    return os.path.isfile(file_path)

def get_current_time():
    """Get the current time as a formatted string."""
    from datetime import datetime
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

## This is includable python module that defines several functions to be used in python code
## This function is called "run_command" and it is used to run a system command.
## It takes in 4 argueemnts: command, pretend, verbose, and veryVerbose.
## The command argument is the command that will be run.
## The pretend argument is a boolean that will print out the command that would be run, but will not actually run the command.
## The verbose argument is a boolean that will print out the command being executed as well as all stdout and stderr to the console and the log file.
## The veryVerbose argument is a boolean that will print out the command being executed as well as all stdout and stderr to the console and the log file.
## The veryVerbose argument is a boolean that will print out the command being executed as well as all stdout and stderr to the console and the log file. It will also print out the calling function and the line number of the calling function.
def run_command(command, pretend=False, verbose=False, veryVerbose=False):
    """Run a system command."""
    if pretend:
        print(f'Pretending to run command: {command}')
        return
    if verbose:
        print(f'Running command: {command}')
    if veryVerbose:
        print(f'Running command: {command} (from {inspect.stack()[1].function} at line {inspect.stack()[1].lineno})')
    process = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    if verbose or veryVerbose:
        print(stdout.decode())
        print(stderr.decode())
        logging.info(f'Command: {command}')
        logging.info(f'Stdout: {stdout.decode()}')
        logging.info(f'Stderr: {stderr.decode()}')
    return process.returncode

