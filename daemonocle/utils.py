import errno
import os
import re
import subprocess


_re_whitespace = re.compile(br'\s+')
_re_non_digits = re.compile(br'[^\d]+')


def proc_get_open_fds(proc):
    """Try really, really hard to get a process's open file descriptors"""
    fd_dir = '/proc/{}/fd'.format(proc.pid)
    if os.path.isdir(fd_dir):
        # We're on Linux
        try:
            os.scandir
        except AttributeError:
            # Python < 3.5
            return [
                int(fd) for fd in os.listdir(fd_dir)
                if os.path.islink(os.path.join(fd_dir, fd))
            ]
        else:
            # Python >= 3.5
            return [
                int(e.name) for e in os.scandir(fd_dir)
                if os.readlink(e.path) != fd_dir
            ]
    else:
        # Not Linux (maybe macOS?)
        try:
            # Try getting FDs from lsof
            cmd = ['lsof', '-a', '-d0-65535', '-p', str(proc.pid)]
            p = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # We'll obviously need to exclude these below
            exclude_fds = {p.stdout.fileno(), p.stderr.fileno()}
            stdout, stderr = p.communicate()
            if p.returncode != 0:
                raise subprocess.CalledProcessError(
                    returncode=p.returncode, cmd=cmd, output=stdout + stderr)
        except (OSError, subprocess.CalledProcessError):
            # lsof failed for some reason. We don't really care why.
            # Just try to find any FDs up to 1024 to be somewhat conservative.
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
