# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

verbose=True
vv=False
quiet=False
pretend=False
force=False
full_command=None
log_file=None

def set_force(value):
    global force
    force=value

def set_verbose(value):
    global verbose
    verbose=value

def set_vv(value):
    global vv
    vv=value

def set_quiet(value):
    global quiet
    quiet=value
    if value==1:
        set_verbose(0)
        set_vv(0)

def set_pretend(value):
    global pretend
    pretend=value

def get_force():
    return(force)

def get_verbose():
    return(verbose)

def get_vv():
    return(vv)

def get_quiet():
    return(quiet)

def get_pretend():
    return(pretend)

def set_full_command(value):
    global full_command
    full_command=value

def get_full_command():
    return(full_command)

def set_log_file(value):
    global log_file
    log_file=value

def get_log_file():
    return(log_file)

