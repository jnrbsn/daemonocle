import os
import posixpath

try:
    from collections.abc import Callable
except ImportError:
    from collections import Callable

from daemonocle._utils import to_bytes
from daemonocle.core import Daemon


class FHSDaemon(Daemon):
    """A Daemon subclass that makes opinionatedly complies with the
    Filesystem Hierarchy Standard"""

    def __init__(self, prog=None, prefix='/opt', **kwargs):
        if prog is not None:
            self.prog = prog
        elif not getattr(self, 'prog', None):
            raise ValueError('prog must be defined for FHSDaemon')

        kwargs.update({
            'chrootdir': None,
            'detach': True,
        })

        if prefix == '/opt':
            kwargs.update({
                'pidfile': '/var/opt/{prog}/run/{prog}.pid'.format(
                    prog=self.prog),
                'stdout_file': '/var/opt/{prog}/log/stdout.log'.format(
                    prog=self.prog),
                'stderr_file': '/var/opt/{prog}/log/stderr.log'.format(
                    prog=self.prog),
            })
        elif prefix == '/usr/local':
            kwargs.update({
                'pidfile': '/var/local/run/{prog}/{prog}.pid'.format(
                    prog=self.prog),
                'stdout_file': '/var/local/log/{prog}/stdout.log'.format(
                    prog=self.prog),
                'stderr_file': '/var/local/log/{prog}/stderr.log'.format(
                    prog=self.prog),
            })
        elif prefix == '/usr':
            kwargs.update({
                'pidfile': '/var/run/{prog}/{prog}.pid'.format(
                    prog=self.prog),
                'stdout_file': '/var/log/{prog}/stdout.log'.format(
                    prog=self.prog),
                'stderr_file': '/var/log/{prog}/stderr.log'.format(
                    prog=self.prog),
            })
        else:
            kwargs.update({
                'pidfile': posixpath.join(
                    prefix, 'run/{prog}.pid'.format(prog=self.prog)),
                'stdout_file': posixpath.join(prefix, 'log/stdout.log'),
                'stderr_file': posixpath.join(prefix, 'log/stderr.log'),
            })

        super(FHSDaemon, self).__init__(**kwargs)


class ExecWorker(Callable):
    """A worker class that simply executes another program"""

    def __init__(self, prog, *args):
        self.prog = to_bytes(prog)
        self.args = tuple(to_bytes(a) for a in args)
        if b'/' in self.prog:
            self.prog = posixpath.realpath(self.prog)

    def __call__(self):  # pragma: no cover
        exec_prog = os.execv if self.prog[0] == b'/' else os.execvp
        exec_prog(self.prog, (self.prog,) + self.args)
