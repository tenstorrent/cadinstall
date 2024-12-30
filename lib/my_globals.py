verbose=True
vv=False
quiet=False
pretend=False

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

def get_verbose():
    return(verbose)

def get_vv():
    return(vv)

def get_quiet():
    return(quiet)

def get_pretend():
    return(pretend)


