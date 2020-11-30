import errno
import os
import posixpath
import re
import subprocess

_re_whitespace = re.compile(br'\s+')
_re_non_digits = re.compile(br'[^\d]+')


def check_dir_exists(path):
    """Check if a directory exists and raise OSError if it doesn't"""
    if not posixpath.exists(path):
        raise OSError(errno.ENOENT, 'No such file or directory', path)
    elif not posixpath.isdir(path):
        raise OSError(errno.ENOTDIR, 'Not a directory', path)


def chroot_path(path, chrootdir):
    """Convert the given non-chroot-relative path into an absolute path
    _inside_ the given chroot directory"""
    path = posixpath.abspath(path)
    chrootdir = posixpath.abspath(chrootdir)
    return posixpath.normpath(
        posixpath.join('/', posixpath.relpath(path, chrootdir)))


def unchroot_path(path, chrootdir):
    """Convert the given chroot-relative path into an absolute path
    _outside_ the given chroot directory"""
    chrootdir = posixpath.abspath(chrootdir)
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
            raise

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
        except (OSError, subprocess.CalledProcessError):
            # lsof failed for some reason. If this is the current process,
            # try to find any FDs up to 1024 (to be somewhat conservative).
            # If it's not the current process, just fail.
            if pid != os.getpid():
                raise RuntimeError(
                    'Unable to get open file descriptors using the "/proc" '
                    'filesystem or the "lsof" command')

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
