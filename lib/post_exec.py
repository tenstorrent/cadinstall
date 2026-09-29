# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

"""
Post-exec script support.

A tool source tree may contain ``.cadinstall.post-exec.sh`` at its root.
The file is not executed as a shell script. It is read during install
prechecks, and every line must be one allowed command operating on one
relative path inside that tree. After the release has been copied and the
install permission pass has finished, the same checked commands are run
against the new release directory only.

The allowlist in ``etc/post_exec_allowed_commands`` can enable or disable
the known commands. It cannot enable any other program: argument grammars
exist only for ``sudo /usr/bin/chown``, ``sudo /usr/bin/chmod``, and
``sudo /usr/bin/chgrp``.
"""

import base64
import errno
import fnmatch
import hashlib
import logging
import os
import re
import shlex
import stat
import subprocess

import lib.my_globals
from lib.utils import check_same_host, run_command, run_command_with_output

logger = logging.getLogger('cadinstall')

POST_EXEC_FILENAME = '.cadinstall.post-exec.sh'

# Grammars the installer knows how to constrain. The allowlist file may only
# name these commands; anything else is refused.
_COMMAND_GRAMMARS = {
    'sudo /usr/bin/chown': 'chown',
    'sudo /usr/bin/chmod': 'chmod',
    'sudo /usr/bin/chgrp': 'chgrp',
}

_DEFAULT_ALLOWED_FILE = os.path.realpath(
    os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'etc', 'post_exec_allowed_commands')
)

# Whole line, after stripping. Hyphen is last so it is literal.
# '*' and '?' are path globs. They are expanded by the installer, not by a shell.
_LINE_RE = re.compile(r'^[A-Za-z0-9_./:+*? -]+$')
# One path component under ./. No leading dot, so '..' cannot match.
_COMPONENT_RE = re.compile(r'^[A-Za-z0-9_*?][A-Za-z0-9._+*?-]*$')
_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_.-]{0,31}$')
_MODE_RE = re.compile(r'^[0-7]{3,4}$')
_HOST_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.-]*$')

_TRUSTED_BINARIES = (
    '/usr/bin/sudo',
    '/usr/bin/chown',
    '/usr/bin/chmod',
    '/usr/bin/chgrp',
)

_MAX_SCRIPT_BYTES = 65536
_MAX_COMMANDS = 100
_MAX_LINE_LENGTH = 512
_SUDO_TIMEOUT = 120

_REMOTE_ERRORS = {
    2: 'illegal relative path',
    3: 'refusing to operate on a symlink',
    4: 'path does not exist in the release',
    5: 'path escapes the release directory',
    6: 'refusing to operate on a non-regular file',
    7: 'refusing to operate on a hard-linked file',
    8: 'release directory does not exist',
}

# Run on the destination host before sudo. Approved paths are printed as
# relative ./ paths. The caller joins those onto the release root itself
# and rejects anything that is absolute or contains '..'.
_REMOTE_CHECK = r"""
import fnmatch, os, re, stat, sys
root_arg = sys.argv[1]
rel = sys.argv[2]
kind = sys.argv[3] if len(sys.argv) > 3 else "chown"
recursive = (len(sys.argv) > 4 and sys.argv[4] == "1")
component_re = re.compile(r"^[A-Za-z0-9_*?][A-Za-z0-9._+*?-]*$")

def die(code, message):
    sys.stderr.write(message + "\n")
    sys.exit(code)

def parts_of(value):
    if value == "./":
        return []
    if (not value.startswith("./")) or value.endswith("/"):
        die(2, "illegal relative path")
    parts = value[2:].split("/")
    if not parts:
        die(2, "illegal relative path")
    for part in parts:
        if part in ("", ".", "..") or (not component_re.match(part)):
            die(2, "illegal relative path")
    return parts

def is_glob(part):
    return ("*" in part) or ("?" in part)

def emit(root, path):
    if path == root:
        sys.stdout.write("./\n")
        return
    relative = os.path.relpath(path, root)
    if relative.startswith("..") or os.path.isabs(relative):
        die(5, "path escapes the release directory")
    sys.stdout.write("./" + relative + "\n")

def no_hardlinks(directory):
    for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
        kept = []
        for name in dirnames:
            if os.path.islink(os.path.join(dirpath, name)):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                continue
            info = os.lstat(path)
            if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                die(7, "refusing to operate on a hard-linked file")

def match_component(base, part):
    if not is_glob(part):
        candidate = os.path.join(base, part)
        if os.path.lexists(candidate):
            return [candidate]
        return []
    matches = []
    for name in sorted(os.listdir(base)):
        if name in (".", "..") or name.startswith("."):
            continue
        if fnmatch.fnmatchcase(name, part):
            matches.append(os.path.join(base, name))
    return matches

parts = parts_of(rel)
root = os.path.realpath(root_arg)
if not os.path.isdir(root):
    die(8, "release directory does not exist")
if not parts:
    if os.path.islink(root_arg):
        die(3, "refusing to operate on a symlink")
    if recursive:
        no_hardlinks(root)
    emit(root, root)
    sys.exit(0)

bases = [root]
for index, part in enumerate(parts):
    last = index == (len(parts) - 1)
    found = []
    for base in bases:
        if os.path.islink(base) or (not os.path.isdir(base)):
            die(3, "refusing to operate on a symlink")
        matched = match_component(base, part)
        if not matched:
            die(4, "path does not exist in the release")
        for candidate in matched:
            parent = os.path.realpath(os.path.dirname(candidate))
            if parent != root and (not parent.startswith(root + os.sep)):
                die(5, "path escapes the release directory")
            if os.path.islink(candidate):
                if (not last) or kind == "chmod":
                    die(3, "refusing to operate on a symlink")
                found.append(candidate)
                continue
            info = os.lstat(candidate)
            final = os.path.realpath(candidate)
            if final != candidate or (not final.startswith(root + os.sep)):
                die(5, "path escapes the release directory")
            if not last:
                if not stat.S_ISDIR(info.st_mode):
                    die(4, "path does not exist in the release")
                found.append(candidate)
                continue
            if stat.S_ISREG(info.st_mode):
                if info.st_nlink > 1:
                    die(7, "refusing to operate on a hard-linked file")
            elif stat.S_ISDIR(info.st_mode):
                if recursive:
                    no_hardlinks(candidate)
            else:
                die(6, "refusing to operate on a non-regular file")
            found.append(final)
    bases = found
for path in bases:
    emit(root, path)
"""


class PostExecError(Exception):
    """The post-exec script is missing a required check or a command failed."""


class PostExecCommand(object):
    def __init__(self, line_no, kind, prefix, operand, relpath, recursive=False):
        self.line_no = line_no
        self.kind = kind
        self.prefix = prefix
        self.operand = operand
        self.relpath = relpath
        self.recursive = recursive

    @property
    def display(self):
        if self.recursive:
            return '%s -R %s %s' % (self.prefix, self.operand, self.relpath)
        return '%s %s %s' % (self.prefix, self.operand, self.relpath)


class PostExecPlan(object):
    def __init__(self, script_path, digest, commands):
        self.script_path = script_path
        self.digest = digest
        self.commands = commands

    def __len__(self):
        return len(self.commands)

    def __bool__(self):
        return bool(self.commands)


def _allowed_commands_file(path):
    if path:
        return path
    return _DEFAULT_ALLOWED_FILE


def load_allowed_commands(path=None):
    """
    Return the enabled command prefixes.

    Unknown lines are an error. The returned set is always a subset of the
    three grammars this module can validate.
    """
    allowed_file = _allowed_commands_file(path)
    if not os.path.isfile(allowed_file):
        raise PostExecError("post-exec allowlist does not exist: %s" % allowed_file)

    enabled = set()
    with open(allowed_file, 'r') as handle:
        for line_no, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            if line not in _COMMAND_GRAMMARS:
                raise PostExecError(
                    "unsupported command in %s line %d: %s" % (allowed_file, line_no, line)
                )
            enabled.add(line)
    if not enabled:
        raise PostExecError("post-exec allowlist is empty: %s" % allowed_file)
    return enabled


def _format_hint():
    return (
        "expected 'sudo /usr/bin/chown [-R] <user>[:<group>] <path>', "
        "'sudo /usr/bin/chmod [-R] <octal-mode> <path>', or "
        "'sudo /usr/bin/chgrp [-R] <group> <path>'. "
        "The path is ./, ./relative/path, or a glob such as ./* and must not contain '..'"
    )


def _parse_operand(kind, token, line_no):
    if kind == 'chmod':
        if not _MODE_RE.match(token):
            raise PostExecError(
                "line %d: chmod mode must be 3 or 4 octal digits, not '%s'" % (line_no, token)
            )
        return token
    if kind == 'chown':
        # chown accepts either an owner or owner:group. An empty side
        # (":group" or "user:") is rejected so the operand stays one
        # explicit account name or one explicit pair.
        parts = token.split(':')
        if len(parts) == 1:
            names = parts
        elif len(parts) == 2 and parts[0] and parts[1]:
            names = parts
        else:
            raise PostExecError(
                "line %d: chown owner must be <user> or <user>:<group>, not '%s'"
                % (line_no, token)
            )
        if not all(_NAME_RE.match(name) for name in names):
            raise PostExecError(
                "line %d: chown user and group must be simple account names, not '%s'"
                % (line_no, token)
            )
        return token
    if kind == 'chgrp':
        if not _NAME_RE.match(token):
            raise PostExecError(
                "line %d: chgrp group must be a simple account name, not '%s'" % (line_no, token)
            )
        return token
    raise PostExecError("line %d: unsupported command '%s'" % (line_no, kind))


def _parse_line(line, line_no, enabled):
    if len(line) > _MAX_LINE_LENGTH:
        raise PostExecError("line %d: command is too long" % line_no)
    if not _LINE_RE.match(line):
        raise PostExecError(
            "line %d: illegal character. %s" % (line_no, _format_hint())
        )
    if '  ' in line:
        raise PostExecError("line %d: commands must be single-spaced" % line_no)

    prefix = None
    for candidate in sorted(enabled, key=len, reverse=True):
        if line.startswith(candidate + ' '):
            prefix = candidate
            break
    if prefix is None:
        raise PostExecError("line %d: command is not allowed. %s" % (line_no, _format_hint()))

    kind = _COMMAND_GRAMMARS[prefix]
    rest = line[len(prefix) + 1:]
    tokens = rest.split(' ')
    recursive = False
    if tokens and tokens[0] == '-R':
        recursive = True
        tokens = tokens[1:]
    if any(token.startswith('-') for token in tokens):
        raise PostExecError(
            "line %d: the only allowed flag is -R. %s" % (line_no, _format_hint())
        )
    if len(tokens) != 2:
        raise PostExecError(
            "line %d: expected an optional -R, one operand, and one relative path. %s"
            % (line_no, _format_hint())
        )
    operand = _parse_operand(kind, tokens[0], line_no)
    relpath = tokens[1]
    try:
        _pattern_parts(relpath)
    except PostExecError as exc:
        raise PostExecError("line %d: %s" % (line_no, exc))
    return PostExecCommand(line_no, kind, prefix, operand, relpath, recursive)


def _read_script_bytes(script_path):
    """Read a regular, non-symlink script. Refuse world-writable files."""
    try:
        listed = os.lstat(script_path)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return None
        raise PostExecError("cannot inspect %s: %s" % (script_path, exc.strerror))

    if stat.S_ISLNK(listed.st_mode):
        raise PostExecError("post-exec script must be a regular file, not a symlink: %s" % script_path)
    if not stat.S_ISREG(listed.st_mode):
        raise PostExecError("post-exec script must be a regular file: %s" % script_path)
    if listed.st_mode & stat.S_IWOTH:
        raise PostExecError("post-exec script is world-writable: %s" % script_path)

    flags = os.O_RDONLY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    if hasattr(os, 'O_CLOEXEC'):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(script_path, flags)
    except OSError as exc:
        raise PostExecError("cannot read %s: %s" % (script_path, exc.strerror))

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise PostExecError("post-exec script must be a regular file: %s" % script_path)
        raw = b''
        while len(raw) <= _MAX_SCRIPT_BYTES:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(fd)

    if len(raw) > _MAX_SCRIPT_BYTES:
        raise PostExecError("post-exec script is larger than %d bytes: %s" % (_MAX_SCRIPT_BYTES, script_path))
    if b'\0' in raw:
        raise PostExecError("post-exec script contains a NUL byte: %s" % script_path)
    if b'\r' in raw.replace(b'\r\n', b'\n'):
        raise PostExecError("post-exec script contains a bare carriage return: %s" % script_path)
    return raw


def _is_glob_component(part):
    return ('*' in part) or ('?' in part)


def _pattern_parts(relpath):
    """
    Split a post-exec path into components under ./.

    ``./`` is the release directory itself and yields an empty list.
    ``..`` is rejected in every position, including ``./../*``.
    """
    if relpath == './':
        return []
    if (not relpath.startswith('./')) or relpath.startswith('//'):
        raise PostExecError(
            "path must stay under ./ and must not contain '..': %s" % relpath
        )
    if relpath.endswith('/'):
        raise PostExecError(
            "path must stay under ./ and must not contain '..': %s" % relpath
        )
    parts = relpath[2:].split('/')
    if not parts:
        raise PostExecError(
            "path must stay under ./ and must not contain '..': %s" % relpath
        )
    for part in parts:
        if part in ('', '.', '..'):
            raise PostExecError(
                "path must stay under ./ and must not contain '..': %s" % relpath
            )
        if not _COMPONENT_RE.match(part):
            raise PostExecError(
                "path must stay under ./ and must not contain '..': %s" % relpath
            )
    return parts


def _concrete_parts(relpath):
    """Like ``_pattern_parts`` but the path can no longer contain a glob."""
    parts = _pattern_parts(relpath)
    for part in parts:
        if _is_glob_component(part):
            raise PostExecError("refusing to pass a wildcard to the command: %s" % relpath)
    return parts


def _inside(root_real, path):
    """True when path is the release root or a non-escaping entry inside it."""
    if os.path.islink(path):
        parent = os.path.realpath(os.path.dirname(path))
        name = os.path.basename(path)
        if name in ('', '.', '..'):
            return False
        return parent == root_real or parent.startswith(root_real + os.sep)
    final = os.path.realpath(path)
    if final != path:
        return False
    return final == root_real or final.startswith(root_real + os.sep)


def _assert_no_hardlinks(directory, relpath):
    """Reject a recursive change that would alter an inode also named elsewhere."""
    for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
        kept = []
        for name in dirnames:
            if os.path.islink(os.path.join(dirpath, name)):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                continue
            info = os.lstat(path)
            if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                raise PostExecError("refusing to operate on a hard-linked file: %s" % relpath)


def _match_component(base, part):
    if not _is_glob_component(part):
        candidate = os.path.join(base, part)
        if os.path.lexists(candidate):
            return [candidate]
        return []
    matches = []
    for name in sorted(os.listdir(base)):
        # Shell globs do not match '.' or '..' or other dot names, so './*'
        # cannot expand to the parent directory.
        if name in ('.', '..') or name.startswith('.'):
            continue
        if fnmatch.fnmatchcase(name, part):
            matches.append(os.path.join(base, name))
    return matches


def resolve_targets(root, relpath, kind, recursive):
    """
    Expand ``relpath`` to absolute paths inside ``root``.

    Globs are expanded here and are never handed to a shell. A symlink is
    not followed. ``chmod`` cannot target a symlink, because it would change
    the file outside the link. ``chown`` and ``chgrp`` are run with ``-h``.
    """
    parts = _pattern_parts(relpath)
    root_real = os.path.realpath(root)
    if not os.path.isdir(root_real):
        raise PostExecError("installation directory does not exist: %s" % root)

    if not parts:
        if os.path.islink(root):
            raise PostExecError("refusing to operate on a symlink: %s" % relpath)
        if recursive:
            _assert_no_hardlinks(root_real, relpath)
        return [root_real]

    bases = [root_real]
    for index, part in enumerate(parts):
        last = index == (len(parts) - 1)
        found = []
        for base in bases:
            if os.path.islink(base) or not os.path.isdir(base):
                raise PostExecError("refusing to operate on a symlink: %s" % relpath)
            matched = _match_component(base, part)
            if not matched:
                raise PostExecError(
                    "path does not exist in the installation: %s" % relpath
                )
            for candidate in matched:
                if not _inside(root_real, candidate):
                    raise PostExecError("path escapes the installation directory: %s" % relpath)
                if os.path.islink(candidate):
                    if (not last) or kind == 'chmod':
                        raise PostExecError("refusing to operate on a symlink: %s" % relpath)
                    found.append(candidate)
                    continue
                info = os.lstat(candidate)
                if not last:
                    if not stat.S_ISDIR(info.st_mode):
                        raise PostExecError("path component is not a directory: %s" % relpath)
                    found.append(candidate)
                    continue
                if stat.S_ISREG(info.st_mode):
                    if info.st_nlink > 1:
                        raise PostExecError("refusing to operate on a hard-linked file: %s" % relpath)
                elif stat.S_ISDIR(info.st_mode):
                    if recursive:
                        _assert_no_hardlinks(candidate, relpath)
                else:
                    raise PostExecError("refusing to operate on a non-regular file: %s" % relpath)
                final = os.path.realpath(candidate)
                if final != candidate or not final.startswith(root_real + os.sep):
                    raise PostExecError("path escapes the installation directory: %s" % relpath)
                found.append(final)
        bases = found
    return bases


def contained_target(root, relpath):
    """Resolve one concrete path inside ``root``."""
    targets = resolve_targets(root, relpath, 'chmod', False)
    if len(targets) != 1:
        raise PostExecError("path must name one file or directory: %s" % relpath)
    return targets[0]


def absolute_release_root(release_root):
    """Normalize the release directory and refuse roots that could escape it."""
    if not isinstance(release_root, str) or not release_root.startswith('/'):
        raise PostExecError("release path must be absolute")
    if '\x00' in release_root or '\n' in release_root or '\r' in release_root:
        raise PostExecError("release path contains illegal characters")
    if any(part == '..' for part in release_root.split('/')):
        raise PostExecError("release path must not contain '..'")
    root = os.path.abspath(release_root)
    if root != '/':
        root = root.rstrip('/')
    if root == '/' or not root.startswith('/'):
        raise PostExecError("refusing to use / as the release directory")
    return root


def lexical_release_path(release_root, relpath):
    """
    Join a validated relative path onto the release root.

    ``..`` is already illegal, and this does not consult the filesystem, so a
    symlink cannot redirect the path that is handed to sudo.
    """
    root = absolute_release_root(release_root)
    parts = _concrete_parts(relpath)
    if not parts:
        return root
    candidate = root
    for part in parts:
        candidate = candidate + '/' + part
    prefix = root + '/'
    if candidate == root or not candidate.startswith(prefix) or '//' in candidate:
        raise PostExecError("path escapes the release directory: %s" % relpath)
    return candidate


def validate_post_exec(src, allowed_commands_file=None):
    """
    Validate ``<src>/.cadinstall.post-exec.sh``.

    Returns an empty plan when the file is absent. Raises PostExecError
    before any install work when the file exists and is not safe.
    """
    if not src or not os.path.isdir(src):
        raise PostExecError("source directory does not exist: %s" % src)

    script_path = os.path.join(src, POST_EXEC_FILENAME)
    raw = _read_script_bytes(script_path)
    if raw is None:
        logger.info("No %s in %s; skipping post-exec" % (POST_EXEC_FILENAME, src))
        return PostExecPlan(None, None, [])

    try:
        text = raw.replace(b'\r\n', b'\n').decode('ascii')
    except UnicodeDecodeError:
        raise PostExecError("post-exec script must be ASCII: %s" % script_path)

    enabled = load_allowed_commands(allowed_commands_file)
    commands = []
    for line_no, raw_line in enumerate(text.split('\n'), 1):
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        command = _parse_line(line, line_no, enabled)
        try:
            resolve_targets(src, command.relpath, command.kind, command.recursive)
        except PostExecError as exc:
            raise PostExecError("line %d: %s" % (line_no, exc))
        commands.append(command)

    if len(commands) > _MAX_COMMANDS:
        raise PostExecError(
            "post-exec script has %d commands; the limit is %d" % (len(commands), _MAX_COMMANDS)
        )

    digest = hashlib.sha256(raw).hexdigest()
    if commands:
        logger.info(
            "Post-exec precheck passed: %d command(s) in %s" % (len(commands), script_path)
        )
        for command in commands:
            logger.info("  post-exec: %s" % command.display)
    else:
        logger.info("Post-exec script %s contains no commands" % script_path)
    return PostExecPlan(script_path, digest, commands)


def _assert_trusted_binary(path):
    if path not in _TRUSTED_BINARIES:
        raise PostExecError("refusing to execute unexpected binary: %s" % path)
    try:
        listed = os.lstat(path)
    except OSError as exc:
        raise PostExecError("required binary is missing: %s (%s)" % (path, exc.strerror))
    if stat.S_ISLNK(listed.st_mode) or not stat.S_ISREG(listed.st_mode):
        raise PostExecError("required binary must be a regular file, not a symlink: %s" % path)
    if os.path.realpath(path) != path:
        raise PostExecError("required binary resolves outside itself: %s" % path)
    info = os.stat(path)
    if info.st_uid != 0:
        raise PostExecError("required binary is not owned by root: %s" % path)
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise PostExecError("required binary is writable by a non-root user: %s" % path)
    if not os.access(path, os.X_OK):
        raise PostExecError("required binary is not executable: %s" % path)


def _sudo_argv(command, targets):
    """
    Build a shell-free sudo argv.

    chown and chgrp get -h so a symlink is not followed, including when -R
    walks the tree. The targets are absolute paths already checked to be
    inside the release. Wildcards are expanded before this runs.
    """
    binary = '/usr/bin/' + command.kind
    if binary not in _TRUSTED_BINARIES:
        raise PostExecError("refusing to execute unexpected binary: %s" % binary)
    if not targets:
        raise PostExecError("refusing to run a command with no path")
    argv = ['/usr/bin/sudo', '-n', binary]
    if command.recursive:
        argv.append('-R')
    if command.kind in ('chown', 'chgrp'):
        argv.append('-h')
    argv.append(command.operand)
    argv.extend(targets)
    return argv


def _confirm_script_unchanged(plan):
    raw = _read_script_bytes(plan.script_path)
    if raw is None:
        raise PostExecError("post-exec script disappeared after the precheck: %s" % plan.script_path)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != plan.digest:
        raise PostExecError(
            "post-exec script changed after the precheck and will not be run: %s" % plan.script_path
        )


def _recheck_command(command):
    """Re-apply the grammar checks to a snapshotted command before running it."""
    if command.kind not in ('chown', 'chmod', 'chgrp'):
        raise PostExecError("refusing to run an unexpected post-exec command")
    if command.prefix != 'sudo /usr/bin/' + command.kind:
        raise PostExecError("refusing to run an unexpected post-exec command")
    _parse_operand(command.kind, command.operand, command.line_no)
    _pattern_parts(command.relpath)
    if command.recursive not in (True, False):
        raise PostExecError("refusing to run an unexpected post-exec command")


def _ssh_command(dest_host, remote_argv):
    if not isinstance(dest_host, str) or not _HOST_RE.match(dest_host):
        raise PostExecError("refusing to use an unsafe destination host name")
    for arg in remote_argv:
        if not isinstance(arg, str) or '\x00' in arg or '\n' in arg:
            raise PostExecError("refusing to pass an unsafe remote argument")
    remote = ' '.join(shlex.quote(arg) for arg in remote_argv)
    return "/usr/bin/ssh %s %s" % (shlex.quote(dest_host), shlex.quote(remote))


def _remote_targets(dest_host, release_root, command):
    """
    Ask the destination host which paths the command may touch.

    The checker prints relative ./ paths. Each one is parsed again locally
    and joined onto the release root, so a printed absolute path or '..'
    cannot become the sudo argument.
    """
    encoded = base64.b64encode(_REMOTE_CHECK.encode('ascii')).decode('ascii')
    launcher = (
        "import base64,sys;"
        "code=base64.b64decode(sys.argv[1]);"
        "sys.argv=['check']+sys.argv[2:];"
        "exec(code)"
    )
    status, output = run_command_with_output(
        _ssh_command(dest_host, [
            '/usr/bin/python3', '-c', launcher, encoded, release_root, command.relpath,
            command.kind, '1' if command.recursive else '0',
        ]),
        log_stdout=False,
        force_run=True,
    )
    if status != 0:
        reason = _REMOTE_ERRORS.get(status, 'path check failed')
        raise PostExecError("%s: %s" % (command.relpath, reason))
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise PostExecError("path does not exist in the release: %s" % command.relpath)
    targets = []
    for line in lines:
        try:
            _concrete_parts(line)
        except PostExecError:
            raise PostExecError("remote path check returned an unsafe path: %s" % command.relpath)
        target = lexical_release_path(release_root, line)
        root = absolute_release_root(release_root)
        if target != root and not target.startswith(root + '/'):
            raise PostExecError("path escapes the release directory: %s" % command.relpath)
        targets.append(target)
    return targets


def _run_local(argv, cwd):
    for arg in argv:
        if not isinstance(arg, str) or '\x00' in arg or '\n' in arg:
            raise PostExecError("refusing to pass an unsafe argument to sudo")
    _assert_trusted_binary('/usr/bin/sudo')
    _assert_trusted_binary(argv[2])
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            shell=False,
            timeout=_SUDO_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise PostExecError("post-exec command timed out: %s" % ' '.join(argv))
    if result.stdout:
        for line in result.stdout.splitlines():
            logger.info(line)
    if result.returncode != 0:
        detail = (result.stderr or '').strip()
        message = "post-exec command failed (exit %s): %s" % (result.returncode, ' '.join(argv))
        if detail:
            message = "%s: %s" % (message, detail)
        raise PostExecError(message)


def _run_remote(dest_host, argv):
    status = run_command(_ssh_command(dest_host, argv))
    if status != 0:
        raise PostExecError(
            "post-exec command failed on %s (exit %s): %s" % (dest_host, status, ' '.join(argv))
        )


def execute_post_exec(plan, release_root, dest_host):
    """
    Run a plan produced by ``validate_post_exec`` inside ``release_root``.

    ``install_tool`` must already have finished, including its permission
    pass. That pass rewrites ownership and mode on the whole tree, so these
    commands have to run afterwards or they would be undone.
    """
    if not plan or not plan.commands:
        return
    if lib.my_globals.get_pretend():
        logger.info("Pretend mode: not running post-exec commands")
        return

    _confirm_script_unchanged(plan)
    release_root = absolute_release_root(release_root)
    local = (check_same_host(dest_host) == 0)
    logger.info("Running post-exec against %s on %s" % (release_root, dest_host))

    root_real = os.path.realpath(release_root)
    for command in plan.commands:
        _recheck_command(command)
        if local:
            targets = resolve_targets(release_root, command.relpath, command.kind, command.recursive)
        else:
            targets = _remote_targets(dest_host, release_root, command)
        for target in targets:
            if local:
                if target != root_real and not target.startswith(root_real + os.sep):
                    raise PostExecError("refusing to operate outside the release: %s" % command.relpath)
            elif target != release_root and not target.startswith(release_root + '/'):
                raise PostExecError("refusing to operate outside the release: %s" % command.relpath)
        argv = _sudo_argv(command, targets)
        logger.info("Post-exec: %s" % ' '.join(argv))
        if local:
            _run_local(argv, release_root)
        else:
            _run_remote(dest_host, argv)
