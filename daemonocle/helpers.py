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

    def __init__(self, name=None, prefix='/opt', **kwargs):
        if name is not None:
            self.name = name
        elif not getattr(self, 'name', None):
            raise ValueError('name must be defined for FHSDaemon')

        kwargs.update({
            'chrootdir': None,
            'detach': True,
        })

        prefix = posixpath.realpath(prefix)

        if prefix == '/opt':
            kwargs.update({
                'pid_file': '/var/opt/{name}/run/{name}.pid'.format(
                    name=self.name),
                'stdout_file': '/var/opt/{name}/log/stdout.log'.format(
                    name=self.name),
                'stderr_file': '/var/opt/{name}/log/stderr.log'.format(
                    name=self.name),
            })
        elif prefix == '/usr/local':
            kwargs.update({
                'pid_file': '/var/local/run/{name}/{name}.pid'.format(
                    name=self.name),
                'stdout_file': '/var/local/log/{name}/stdout.log'.format(
                    name=self.name),
                'stderr_file': '/var/local/log/{name}/stderr.log'.format(
                    name=self.name),
            })
        elif prefix == '/usr':
            kwargs.update({
                'pid_file': '/var/run/{name}/{name}.pid'.format(
                    name=self.name),
                'stdout_file': '/var/log/{name}/stdout.log'.format(
                    name=self.name),
                'stderr_file': '/var/log/{name}/stderr.log'.format(
                    name=self.name),
            })
        else:
            kwargs.update({
                'pid_file': posixpath.join(
                    prefix, 'run/{name}.pid'.format(name=self.name)),
                'stdout_file': posixpath.join(prefix, 'log/stdout.log'),
                'stderr_file': posixpath.join(prefix, 'log/stderr.log'),
            })

        super(FHSDaemon, self).__init__(**kwargs)


class ExecWorker(Callable):
    """A worker class that simply executes another program"""

    def __init__(self, name, *args):
        self.name = to_bytes(name)
        self.args = tuple(to_bytes(a) for a in args)
        if b'/' in self.name:
            self.name = posixpath.realpath(self.name)

    def __call__(self):  # pragma: no cover
        exec_prog = os.execv if self.name[0] == b'/' else os.execvp
        exec_prog(self.name, (self.name,) + self.args)
