import os
import posixpath
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from operator import itemgetter

import click
import psutil

from daemonocle._utils import (
    format_elapsed_time, json_encode, to_bytes, waitstatus_to_exitcode)
from daemonocle.core import Daemon, expose_action, get_action, list_actions
from daemonocle.exceptions import DaemonError


class FHSDaemon(Daemon):
    """A Daemon subclass that makes opinionatedly complies with the
    Filesystem Hierarchy Standard"""

    def __init__(
            self, name=None, prefix='/opt', log_prefix='', **kwargs):
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
                'pid_file': '/var/opt/{name}/run/{name}.pid',
                'stdout_file': '/var/opt/{name}/log/{log_prefix}out.log',
                'stderr_file': '/var/opt/{name}/log/{log_prefix}err.log',
            })
        elif prefix == '/usr/local':
            kwargs.update({
                'pid_file': '/var/local/run/{name}/{name}.pid',
                'stdout_file': '/var/local/log/{name}/{log_prefix}out.log',
                'stderr_file': '/var/local/log/{name}/{log_prefix}err.log',
            })
        elif prefix == '/usr':
            kwargs.update({
                'pid_file': '/var/run/{name}/{name}.pid',
                'stdout_file': '/var/log/{name}/{log_prefix}out.log',
                'stderr_file': '/var/log/{name}/{log_prefix}err.log',
            })
        else:
            kwargs.update({
                'pid_file': posixpath.join(prefix, 'run/{name}.pid'),
                'stdout_file': posixpath.join(
                    prefix, 'log/{log_prefix}out.log'),
                'stderr_file': posixpath.join(
                    prefix, 'log/{log_prefix}err.log'),
            })

        # Format paths
        for key in ('pid_file', 'stdout_file', 'stderr_file'):
            kwargs[key] = kwargs[key].format(
                name=self.name, log_prefix=log_prefix)

        if 'work_dir' in kwargs:
            work_dir = posixpath.realpath(kwargs['work_dir'])
            if work_dir == prefix and not posixpath.isdir(work_dir):
                # Normally, the work_dir is required to exist, but if the
                # work_dir is the same as the prefix, automatically create it
                # if it doesn't exist.
                umask = kwargs.get('umask', 0o22)
                uid = kwargs.get('uid', os.getuid())
                gid = kwargs.get('gid', os.getgid())
                os.makedirs(work_dir, 0o777 & ~umask)
                os.chown(work_dir, uid, gid)

        super(FHSDaemon, self).__init__(**kwargs)


class MultiDaemon(object):
    """Daemon wrapper class that manages multiple copies of the same worker"""

    def __init__(self, num_workers, daemon_cls=Daemon, **daemon_kwargs):
        if num_workers < 1:
            raise DaemonError('num_workers must be >= 1 for MultiDaemon')

        self.num_workers = num_workers
        self.worker = daemon_kwargs.get('worker', None)
        self._daemons = []

        kwargs_to_format = {'name', 'work_dir'}
        if issubclass(daemon_cls, FHSDaemon):
            kwargs_to_format.add('prefix')
        else:
            kwargs_to_format.update(('pid_file', 'stdout_file', 'stderr_file'))

        pid_files = set()
        for n in range(self.num_workers):
            kwargs = daemon_kwargs.copy()
            kwargs.update({
                'chrootdir': None,
                'detach': True,
            })

            for key in kwargs_to_format:
                if key in kwargs:
                    kwargs[key] = kwargs[key].format(n=n)

            daemon = daemon_cls(**kwargs)
            # Enable multi mode
            daemon.worker_id = n

            if daemon.pid_file is None:
                raise DaemonError('pid_file must be defined for MultiDaemon')
            pid_files.add(daemon.pid_file)

            self._daemons.append(daemon)

        if len(pid_files) < self.num_workers:
            raise DaemonError('PID files must be unique for MultiDaemon')

    @classmethod
    def list_actions(cls):
        return list_actions(cls)

    def get_action(self, action):
        return get_action(self, action)

    def do_action(self, action, *args, **kwargs):
        func = self.get_action(action)
        return func(*args, **kwargs)

    def cli(self, *args, **kwargs):
        from daemonocle.cli import DaemonCLI
        cli = DaemonCLI(daemon=self)
        return cli(*args, **kwargs)

    @expose_action
    def start(self, worker_id=None, debug=False, *args, **kwargs):
        """Start the daemon."""
        if worker_id is not None:
            daemons = [self._daemons[worker_id]]
        else:
            daemons = self._daemons

        # Do first part of detaching
        pid = os.fork()
        if pid:
            status = os.waitpid(pid, 0)
            exit(waitstatus_to_exitcode(status[1]))
        # All workers will be in the same session, and each worker will
        # be in its own process group (handled in Daemon class).
        os.setsid()

        try:
            ctx = click.get_current_context()
        except RuntimeError:
            ctx = None

        for daemon in daemons:
            if ctx is not None:
                ctx.obj = daemon
            daemon.start(debug=debug, *args, **kwargs)

    @expose_action
    def stop(self, worker_id=None, timeout=None, force=False):
        """Stop the daemon."""
        if worker_id is not None:
            daemons = [self._daemons[worker_id]]
        else:
            daemons = self._daemons
        for daemon in daemons:
            daemon.stop(timeout=timeout, force=force)

    @expose_action
    def restart(
            self, worker_id=None, timeout=None, force=False, debug=False,
            *args, **kwargs):
        """Stop then start the daemon."""
        self.stop(worker_id=worker_id, timeout=timeout, force=force)
        self.start(worker_id=worker_id, debug=debug, *args, **kwargs)

    def get_status_single(self, worker_id, fields=None):
        return self._daemons[worker_id].get_status(fields=fields)

    def get_status(self, fields=None):
        """Get the statuses of all the workers in parallel."""
        statuses = []
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            future_to_worker_id = {}
            for n in range(self.num_workers):
                future = executor.submit(
                    self.get_status_single, n, fields=fields)
                future_to_worker_id[future] = n

            for future in as_completed(future_to_worker_id):
                n = future_to_worker_id[future]
                statuses.append((n, future.result()))

        return [s[1] for s in sorted(statuses, key=itemgetter(0))]

    @expose_action
    def status(self, worker_id=None, json=False, fields=None):
        """Get the status of the daemon."""
        if worker_id is not None:
            statuses = [self.get_status_single(worker_id, fields=fields)]
        else:
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
        self.__doc__ = 'Run "{}" as a daemon.'.format(
            self.name.decode('ascii', errors='backslashreplace'))

    def __call__(self):  # pragma: no cover
        exec_prog = os.execv if self.name[0] == b'/' else os.execvp
        exec_prog(self.name, (self.name,) + self.args)
