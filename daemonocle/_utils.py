import errno
import json
import os
import posixpath
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import psutil

from .exceptions import DaemonEnvironmentError

_re_whitespace = re.compile(br'\s+')
_re_non_digits = re.compile(br'[^\d]+')


def to_bytes(x):
    if isinstance(x, bytes):
        return x
    return x.encode('utf-8')


def check_dir_exists(path):
    """Check if a directory exists and raise OSError if it doesn't"""
    if not posixpath.exists(path):
        raise OSError(errno.ENOENT, 'No such file or directory', path)
    elif not posixpath.isdir(path):
        raise OSError(errno.ENOTDIR, 'Not a directory', path)


def chroot_path(path, chrootdir):
    """Convert the given non-chroot-relative path into an absolute path
    _inside_ the given chroot directory"""
    path = posixpath.realpath(path)
    chrootdir = posixpath.realpath(chrootdir)
    return posixpath.normpath(
        posixpath.join('/', posixpath.relpath(path, chrootdir)))


def unchroot_path(path, chrootdir):
    """Convert the given chroot-relative path into an absolute path
    _outside_ the given chroot directory"""
    chrootdir = posixpath.realpath(chrootdir)
    return posixpath.normpath(posixpath.join(chrootdir, path.lstrip('/')))


def proc_get_open_fds(pid=None):
    """Try really, really hard to get a process's open file descriptors"""
    pid = pid or os.getpid()

    fd_dir = '/proc/{}/fd'.format(pid)
    try:
        # Try /proc on Linux first
        try:
            os.scandir
        except AttributeError:
            # Python < 3.5
            return [
                int(fd) for fd in os.listdir(fd_dir)
                if posixpath.islink(posixpath.join(fd_dir, fd))
            ]
        else:
            # Python >= 3.5
            return [
                int(e.name) for e in os.scandir(fd_dir)
                if os.readlink(e.path) != fd_dir
            ]
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise DaemonEnvironmentError(
                'Unable to get open file descriptors using "/proc/<pid>/fd" '
                '({error})'.format(error=str(e)))

        # We're not on Linux (maybe macOS?)
        try:
            # Try getting FDs from lsof
            cmd = ['lsof', '-a', '-d0-65535', '-p', str(pid)]
            p = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # We'll obviously need to exclude these below
            exclude_fds = {p.stdout.fileno(), p.stderr.fileno()}
            stdout, stderr = p.communicate()
            if p.returncode != 0 or not stdout.strip():
                raise subprocess.CalledProcessError(
                    returncode=p.returncode, cmd=cmd, output=stdout + stderr)
        except Exception as e:
            # lsof failed for some reason. If this is the current process,
            # try to find any FDs up to 1024 (to be somewhat conservative).
            # If it's not the current process, just fail.
            if pid != os.getpid():
                raise DaemonEnvironmentError(
                    'Unable to get open file descriptors using "lsof" '
                    '({error})'.format(error=str(e)))

            fds = []
            for fd in range(1024):
                try:
                    os.fstat(fd)
                except OSError as e:
                    if e.errno == errno.EBADF:
                        # Bad file descriptor
                        continue
                    raise
                else:
                    fds.append(fd)
            return fds
        else:
            # Parse the output of lsof
            lines = [line.strip() for line in stdout.strip().split(b'\n')]
            # Find which field contains the FD
            field_names = [f.lower() for f in _re_whitespace.split(lines[0])]
            fd_field_index = field_names.index(b'fd')

            fds = []
            for line in lines[1:]:
                fields = [f.lower() for f in _re_whitespace.split(line)]
                # Strip out non-digit characters and convert to int
                fd = int(_re_non_digits.sub(b'', fields[fd_field_index]))
                if fd in exclude_fds:
                    continue
                fds.append(fd)

            return fds


def json_encode(data):
    return json.dumps(
        data, separators=(', ', ': '), indent=None, sort_keys=True)


def format_elapsed_time(seconds):
    """Format number of seconds as days, hours, & minutes like '12d 3h 45m'"""
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    result = '{minutes}m'.format(minutes=minutes)

    if hours:
        days, hours = divmod(hours, 24)
        result = '{hours}h {prev}'.format(hours=hours, prev=result)

        if days:
            result = '{days}d {prev}'.format(days=days, prev=result)

    return result


def get_proc_info(proc, fields):
    if 'cpu_percent' in fields:
        proc.cpu_percent()
        time.sleep(1)
    return proc.as_dict(attrs=fields)


def get_proc_group_info(pgid, fields):
    group_procs = []
    for proc in psutil.process_iter():
        try:
            if os.getpgid(proc.pid) == pgid and proc.pid != 0:
                group_procs.append(proc)
        except (psutil.Error, OSError):
            continue

    if len(group_procs) == 1:
        return {group_procs[0].pid: get_proc_info(group_procs[0], fields)}

    group_info = {}
    with ThreadPoolExecutor(max_workers=len(group_procs)) as executor:
        future_to_pid = {
            executor.submit(get_proc_info, proc, fields): proc.pid
            for proc in group_procs}
        for future in as_completed(future_to_pid):
            pid = future_to_pid[future]
            try:
                group_info[pid] = future.result()
            except psutil.Error:
                continue

    return group_info
