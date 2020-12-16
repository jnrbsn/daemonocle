import os
import posixpath
from concurrent.futures import ThreadPoolExecutor, as_completed
from operator import itemgetter

try:
    from collections.abc import Callable
except ImportError:
    from collections import Callable

import click
import psutil

from daemonocle._utils import (
    format_elapsed_time, json_encode, to_bytes, waitstatus_to_exitcode)
from daemonocle.core import Daemon
from daemonocle.exceptions import DaemonError


class FHSDaemon(Daemon):
    """A Daemon subclass that makes opinionatedly complies with the
    Filesystem Hierarchy Standard"""

    def __init__(self, name=None, prefix='/opt', **kwargs):
        if name is not None:
            self.name = name
        elif not getattr(self, 'name', None):
            raise DaemonError('name must be defined for FHSDaemon')

        kwargs.update({
            'chrootdir': None,
            'detach': True,
        })

        prefix = posixpath.realpath(prefix)

        if prefix == '/opt':
            kwargs.update({
                'pid_file': '/var/opt/{name}/run/{name}.pid'.format(
                    name=self.name),
                'stdout_file': '/var/opt/{name}/log/out.log'.format(
                    name=self.name),
                'stderr_file': '/var/opt/{name}/log/err.log'.format(
                    name=self.name),
            })
        elif prefix == '/usr/local':
            kwargs.update({
                'pid_file': '/var/local/run/{name}/{name}.pid'.format(
                    name=self.name),
                'stdout_file': '/var/local/log/{name}/out.log'.format(
                    name=self.name),
                'stderr_file': '/var/local/log/{name}/err.log'.format(
                    name=self.name),
            })
        elif prefix == '/usr':
            kwargs.update({
                'pid_file': '/var/run/{name}/{name}.pid'.format(
                    name=self.name),
                'stdout_file': '/var/log/{name}/out.log'.format(
                    name=self.name),
                'stderr_file': '/var/log/{name}/err.log'.format(
                    name=self.name),
            })
        else:
            kwargs.update({
                'pid_file': posixpath.join(
                    prefix, 'run/{name}.pid'.format(name=self.name)),
                'stdout_file': posixpath.join(prefix, 'log/out.log'),
                'stderr_file': posixpath.join(prefix, 'log/err.log'),
            })

        super(FHSDaemon, self).__init__(**kwargs)


class MultiDaemon(object):
    """Daemon wrapper class that manages multiple copies of the same worker"""

    def __init__(self, num_workers, daemon_cls=Daemon, **daemon_kwargs):
        self.num_workers = max(num_workers, 2)
        self.worker = daemon_kwargs.get('worker', None)
        self._daemons = []

        kwargs_to_format = {'name', 'work_dir'}
        if issubclass(daemon_cls, FHSDaemon):
            kwargs_to_format.add('prefix')
        else:
            kwargs_to_format.update(('pid_file', 'stdout_file', 'stderr_file'))

        pid_files = set()
        for n in range(num_workers):
            kwargs = daemon_kwargs.copy()
            kwargs.update({
                'chrootdir': None,
                'detach': True,
            })

            for key in kwargs_to_format:
                if key in kwargs:
                    kwargs[key] = kwargs[key].format(n=n)

            daemon = daemon_cls(**kwargs)
            # Turn on hidden flag
            daemon._multi = True

            if daemon.pid_file is None:
                raise DaemonError('pid_file must be defined for MultiDaemon')
            pid_files.add(daemon.pid_file)

            self._daemons.append(daemon)

        if len(pid_files) < self.num_workers:
            raise DaemonError('PID files must be unique for MultiDaemon')

    @classmethod
    def list_actions(cls):
        return ['start', 'stop', 'restart', 'status']

    def get_action(self, action):
        if action not in self.list_actions():
            raise DaemonError(
                'Invalid action "{action}"'.format(action=action))
        return getattr(self, action)

    def do_action(self, action, *args, **kwargs):
        func = self.get_action(action)
        return func(*args, **kwargs)

    def cli(self):
        from daemonocle.cli import DaemonCLI
        cli = DaemonCLI(daemon=self)
        return cli()

    def start(self, debug=False, *args, **kwargs):
        """Start the daemon."""
        # Do first part of detaching
        pid = os.fork()
        if pid:
            status = os.waitpid(pid, 0)
            exit(waitstatus_to_exitcode(status[1]))
        # All workers will be in the same session, and each worker will
        # be in its own process group (handled in Daemon class).
        os.setsid()

        for daemon in self._daemons:
            daemon.start(debug=debug, *args, **kwargs)

    def stop(self, timeout=None, force=False):
        """Stop the daemon."""
        for daemon in self._daemons:
            daemon.stop(timeout=timeout, force=force)

    def restart(self, timeout=None, force=False, debug=False, *args, **kwargs):
        """Stop then start the daemon."""
        self.stop(timeout=timeout, force=force)
        self.start(debug=debug, *args, **kwargs)

    def _get_status_single(self, daemon_id, fields=None):
        return self._daemons[daemon_id].get_status(fields=fields)

    def get_status(self, fields=None):
        """Get the statuses of all the workers in parallel."""
        statuses = []
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            future_to_daemon_id = {}
            for n in range(self.num_workers):
                future = executor.submit(
                    self._get_status_single, n, fields=fields)
                future_to_daemon_id[future] = n

            for future in as_completed(future_to_daemon_id):
                n = future_to_daemon_id[future]
                statuses.append((n, future.result()))

        return [s[1] for s in sorted(statuses, key=itemgetter(0))]

    def status(self, json=False, fields=None):
        """Get the status of the daemon."""
        statuses = self.get_status(fields=fields)

        if json:
            status_width = max(len(json_encode(s)) for s in statuses)
            term_width, term_height = click.get_terminal_size()

            if status_width + 3 > term_width:
                message = json_encode(statuses, pretty=True)
            else:
                message = ['[']
                for i, status in enumerate(statuses):
                    message.append(
                        '  ' + json_encode(status) +
                        (',' if i < len(statuses) - 1 else '')
                    )
                message.append(']')
                message = '\n'.join(message)
        else:
            message = []
            for status in statuses:
                if status.get('status') == psutil.STATUS_DEAD:
                    message.append('{name} -- not running'.format(
                        name=status['name']))
                else:
                    status['uptime'] = format_elapsed_time(status['uptime'])
                    template = (
                        '{name} -- pid: {pid}, status: {status}, '
                        'uptime: {uptime}, %cpu: {cpu_percent:.1f}, '
                        '%mem: {memory_percent:.1f}')
                    message.append(template.format(**status))
            message = '\n'.join(message)

        click.echo(message)


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
