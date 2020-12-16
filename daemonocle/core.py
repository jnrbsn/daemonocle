"""Core functionality of daemonocle"""

import errno
import os
import posixpath
import resource
import signal
import socket
import subprocess
import sys
import time
from math import fsum

import click
import psutil

from ._utils import (
    check_dir_exists, chroot_path, exit, format_elapsed_time,
    get_proc_group_children, get_proc_group_info, json_encode,
    proc_get_open_fds, signal_number_to_name, unchroot_path,
    waitstatus_to_exitcode)
from .exceptions import DaemonError

if sys.version_info.major < 3:
    text = unicode  # noqa: F821
else:
    text = str


def expose_action(func):
    """This decorator makes a method into an action."""
    func.__daemonocle_exposed__ = True
    return func


class Daemon(object):
    """This is the main class for creating a daemon using daemonocle."""

    def __init__(
        self,
        # Basic stuff
        name=None,
        worker=None,
        detach=True,
        # Paths
        pid_file=None,
        work_dir='/',
        stdout_file=None,
        stderr_file=None,
        chroot_dir=None,
        # Environmental stuff that most people probably won't use
        uid=None,
        gid=None,
        umask=0o22,
        close_open_files=False,
        # Related to stopping / shutting down
        shutdown_callback=None,
        stop_timeout=10,
        # Deprecated aliases
        prog=None,
        pidfile=None,
        workdir='/',
        chrootdir=None,
    ):
        """Create a new Daemon object."""

        # Deprecated aliases
        name = name or prog
        pid_file = pid_file or pidfile
        work_dir = work_dir or workdir
        chroot_dir = chroot_dir or chrootdir

        if name is not None:
            self.name = name
        elif not getattr(self, 'name', None):
            self.name = posixpath.basename(sys.argv[0])

        if worker is not None or not callable(getattr(self, 'worker', None)):
            self.worker = worker

        self.detach = detach and self._is_detach_necessary()

        self.pid_file = pid_file
        self.work_dir = work_dir
        self.stdout_file = stdout_file
        self.stderr_file = stderr_file
        self.chroot_dir = chroot_dir

        self.uid = uid if uid is not None else os.getuid()
        self.gid = gid if gid is not None else os.getgid()
        self.umask = umask
        self.close_open_files = close_open_files

        self.shutdown_callback = shutdown_callback
        self.stop_timeout = stop_timeout

        if self.chroot_dir is not None:
            self.chroot_dir = posixpath.realpath(self.chroot_dir)
            check_dir_exists(self.chroot_dir)

            self.work_dir = (
                unchroot_path(self.work_dir, self.chroot_dir)
                if self.work_dir else self.chroot_dir)

            for attr in ('pid_file', 'stdout_file', 'stderr_file'):
                path = getattr(self, attr)
                setattr(self, attr, (
                    unchroot_path(path, self.chroot_dir) if path else None))
        else:
            self.work_dir = posixpath.realpath(self.work_dir)
            for attr in ('pid_file', 'stdout_file', 'stderr_file'):
                path = getattr(self, attr)
                if path is not None:
                    setattr(self, attr, posixpath.realpath(path))

        check_dir_exists(self.work_dir)

        self._pid_fd = None
        self._shutdown_complete = False
        self._orig_workdir = '/'
        # Experimental feature
        self._multi = False

    @classmethod
    def _echo(cls, message, stderr=False, color=None):
        """Print a message to STDOUT or STDERR."""
        message = click.style(message, fg=color)
        click.echo(message, nl=False, err=stderr)

    @classmethod
    def _echo_ok(cls):
        """Print OK for success."""
        cls._echo('OK\n', color='green')

    @classmethod
    def _echo_failed(cls):
        """Print FAILED on error."""
        cls._echo('FAILED\n', color='red')

    @classmethod
    def _echo_error(cls, message):
        """Print an error message to STDERR."""
        cls._echo('ERROR: {message}\n'.format(message=message),
                  stderr=True, color='red')

    @classmethod
    def _echo_warning(cls, message):
        """Print an warning message to STDERR."""
        cls._echo('WARNING: {message}\n'.format(message=message),
                  stderr=True, color='yellow')

    def _maybe_exit(self, exitcode=0):
        """Exit with or return the given exit code (multi mode)."""
        if self._multi:
            return exitcode
        else:
            exit(exitcode)

    def _setup_dirs(self):
        """Create the various directories if necessary."""
        for attr in ('pid_file', 'stdout_file', 'stderr_file'):
            file_path = getattr(self, attr)
            if file_path is None:
                continue
            dir_path = posixpath.dirname(file_path)
            if not posixpath.isdir(dir_path):
                # Create the directory with sensible mode and ownership
                os.makedirs(dir_path, 0o777 & ~self.umask)
                os.chown(dir_path, self.uid, self.gid)

    def _read_pid_file(self):
        """Read the PID file and check to make sure it's not stale."""
        if self.pid_file is None:
            return None

        if not posixpath.isfile(self.pid_file):
            return None

        # Read the PID file
        with open(self.pid_file, 'r') as fp:
            try:
                pid = int(fp.read())
            except ValueError:
                self._echo_warning('Empty or broken PID file {pid_file}; '
                                   'removing'.format(pid_file=self.pid_file))
                pid = None

        if pid is not None and psutil.pid_exists(pid):
            return pid
        else:
            # Remove the stale PID file
            os.remove(self.pid_file)
            return None

    def _write_pid_file(self):
        """Create, write to, and lock the PID file."""
        flags = os.O_CREAT | os.O_RDWR | os.O_TRUNC
        try:
            # O_CLOEXEC is only available on Unix and Python >= 3.3
            flags |= os.O_CLOEXEC
        except AttributeError:
            pass
        try:
            # O_EXLOCK is an extension that might not be present if not
            # defined in the underlying C library
            flags |= os.O_EXLOCK
        except AttributeError:
            pass
        self._pid_fd = os.open(self.pid_file, flags, 0o666 & ~self.umask)
        os.write(self._pid_fd, b'%d\n' % os.getpid())

    def _close_pid_file(self):
        """Closes and removes the PID file."""
        if self._pid_fd is not None:
            os.close(self._pid_fd)
        try:
            os.remove(self.pid_file)
        except OSError as ex:
            if ex.errno != errno.ENOENT:
                raise

    @classmethod
    def _prevent_core_dump(cls):
        """Prevent the process from generating a core dump."""
        try:
            # Try to get the current limit
            resource.getrlimit(resource.RLIMIT_CORE)
        except ValueError:
            # System doesn't support the RLIMIT_CORE resource limit
            return
        else:
            # Set the soft and hard limits for core dump size to zero
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def _setup_environment(self):
        """Setup the environment for the daemon."""
        # Save the original working directory so that reload can launch
        # the new process with the same arguments as the original
        self._orig_workdir = os.getcwd()

        if self.chroot_dir is not None:
            try:
                # Change the root directory
                os.chdir(self.chroot_dir)
                os.chroot(self.chroot_dir)
            except Exception as ex:
                raise DaemonError('Unable to change root directory '
                                  '({error})'.format(error=str(ex)))
            else:
                self.work_dir = chroot_path(self.work_dir, self.chroot_dir)
                for attr in ('pid_file', 'stdout_file', 'stderr_file'):
                    path = getattr(self, attr)
                    if path is None:
                        continue
                    setattr(self, attr, chroot_path(path, self.chroot_dir))

        # Prevent the process from generating a core dump
        self._prevent_core_dump()

        try:
            # Switch directories
            os.chdir(self.work_dir)
        except Exception as ex:
            raise DaemonError('Unable to change working directory '
                              '({error})'.format(error=str(ex)))

        # Create the various directories if necessary
        self._setup_dirs()

        try:
            # Set file creation mask
            os.umask(self.umask)
        except Exception as ex:
            raise DaemonError('Unable to change file creation mask '
                              '({error})'.format(error=str(ex)))

        try:
            # Switch users
            os.setgid(self.gid)
            os.setuid(self.uid)
        except Exception as ex:
            raise DaemonError('Unable to setuid or setgid '
                              '({error})'.format(error=str(ex)))

    def _redirect_std_streams(self):
        """Redirect STDOUT and STDERR, and close STDIN"""

        flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND
        mode = 0o666 & ~self.umask

        stdout_file_fd = None
        stderr_file_fd = None

        # Flush buffers
        sys.stdout.flush()
        sys.stderr.flush()

        if self.stdout_file is not None:
            stdout_file_fd = os.open(self.stdout_file, flags, mode)
            os.close(1)
            os.dup2(stdout_file_fd, 1)

        if self.stderr_file is not None:
            if self.stdout_file == self.stderr_file:
                # STDOUT and STDERR are going to the same place
                stderr_file_fd = stdout_file_fd
            else:
                stderr_file_fd = os.open(self.stderr_file, flags, mode)
            os.close(2)
            os.dup2(stderr_file_fd, 2)

        # Close the original FDs that we duplicated to FDs 1 and 2
        if stdout_file_fd is not None:
            os.close(stdout_file_fd)
        if stderr_file_fd is not None and stdout_file_fd != stderr_file_fd:
            os.close(stderr_file_fd)

        try:
            devnull_fd = os.open(os.devnull, os.O_RDWR)
        except OSError as e:
            if e.errno == errno.ENOENT:
                # If we're in a chroot jail, /dev/null might not exist
                message = 'The "{devnull}" device does not exist.'
                if self.chroot_dir is not None:
                    message += (
                        ' It must be created within the chroot directory '
                        'for the daemon to function correctly.')
                raise DaemonError(message.format(devnull=os.devnull))
            raise

        # Attach STDIN to /dev/null
        os.close(0)
        os.dup2(devnull_fd, 0)

        # If we haven't redirected STDOUT and/or STDERR elsewhere,
        # redirect them to /dev/null
        if self.stdout_file is None:
            os.close(1)
            os.dup2(devnull_fd, 1)
        if self.stderr_file is None:
            os.close(2)
            os.dup2(devnull_fd, 2)

        os.close(devnull_fd)

    def _reset_file_descriptors(self):
        """Close open file descriptors and redirect standard streams."""
        self._redirect_std_streams()

        if self.close_open_files:
            # Close all open files except the standard streams and the
            # PID file, if there is one
            exclude_fds = {0, 1, 2}
            if self._pid_fd:
                exclude_fds.add(self._pid_fd)

            for fd in proc_get_open_fds():
                if fd in exclude_fds:
                    continue
                try:
                    os.close(fd)
                except OSError as e:
                    if e.errno == errno.EBADF:
                        # Bad file descriptor. Maybe it got closed already?
                        continue
                    raise

    @classmethod
    def _is_socket(cls, stream):
        """Check if the given stream is a socket."""
        try:
            fd = stream.fileno()
        except ValueError:
            # If it has no file descriptor, it's not a socket
            return False

        try:
            # These will raise a socket.error if it's not a socket
            sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_RAW)
            sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
        except socket.error as ex:
            if ex.args[0] != errno.ENOTSOCK:
                # It must be a socket
                return True
        else:
            # If an exception wasn't raised, it's a socket
            return True

    @classmethod
    def _pid_is_alive(cls, pid, timeout):
        """Check if a PID is alive with a timeout."""
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return False

        try:
            proc.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            return True

        return False

    @classmethod
    def _is_in_container(cls):
        """Check if we're running inside a container."""
        if not posixpath.exists('/proc/1/cgroup'):
            # If not on Linux, just assume we're not in a container
            return False

        container_types = {
            b'docker',
            b'docker-ce',
            b'ecs',
            b'kubepods',
            b'lxc',
        }

        with open('/proc/1/cgroup', 'rb') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                name = line.split(b':', 2)[2]
                name_parts = set(name.strip(b'/').split(b'/'))
                if name_parts & container_types:
                    return True

        return False

    @classmethod
    def _is_detach_necessary(cls):
        """Check if detaching the process is even necessary."""
        if os.getpid() == 1:
            # We're likely the only process in a container
            return False

        if os.getppid() == 1 and not cls._is_in_container():
            # Process was started by PID 1, but NOT in a container
            return False

        if cls._is_socket(sys.stdin):
            # If STDIN is a socket, the daemon was started by a super-server
            return False

        return True

    def _detach_process(self):
        """Detach the process via the standard double-fork method with
        some extra magic."""
        if not self._multi:
            # First fork to return control to the shell
            pid = os.fork()
            if pid > 0:
                # Wait for the first child, because it's going to wait and
                # check to make sure the second child is actually running
                # before exiting
                status = os.waitpid(pid, 0)
                exit(waitstatus_to_exitcode(status[1]))

            # Become a session leader and process group leader
            os.setsid()

        # Fork again so the session group leader can exit and to ensure
        # we can never regain a controlling terminal
        pid = os.fork()
        if pid > 0:
            time.sleep(1)
            # After waiting one second, check to make sure the second
            # child hasn't become a zombie already
            status = os.waitpid(pid, os.WNOHANG)
            if status[0] == pid:
                # The child is already gone for some reason
                exitcode = waitstatus_to_exitcode(status[1])
                self._echo_failed()
                self._echo_error('Child exited immediately with exit '
                                 'code {code}'.format(code=exitcode))
            else:
                self._echo_ok()
                exitcode = 0
            return self._maybe_exit(exitcode)
        elif self._multi:
            # In multi mode, make the worker process a process group
            # leader since all workers will be in the same session.
            os.setpgid(0, 0)

        self._reset_file_descriptors()

        return None

    @classmethod
    def _orphan_this_process(cls, wait_for_parent=False):
        """Orphan the current process by forking and then waiting for
        the parent to exit."""
        # The current PID will be the PPID of the forked child
        ppid = os.getpid()

        pid = os.fork()
        if pid > 0:
            # Exit parent
            exit(0)

        if wait_for_parent and cls._pid_is_alive(ppid, timeout=1):
            raise DaemonError(
                'Parent did not exit while trying to orphan process')

    @classmethod
    def _fork_and_supervise_child(cls):
        """Fork a child and then watch the process group until there are
        no processes in it."""
        # Become a process group leader if we're not already one
        try:
            os.setpgid(0, 0)
        except OSError as e:
            if e.errno != errno.EPERM:
                raise

        pid = os.fork()
        if pid == 0:
            # Fork again but orphan the child this time so we'll have
            # the original parent and the second child which is orphaned
            # so we don't have to worry about it becoming a zombie
            cls._orphan_this_process()
            return
        # Since this process is not going to exit, we need to call
        # os.waitpid() so that the first child doesn't become a zombie
        os.waitpid(pid, 0)

        while True:
            try:
                # Look for child processes in the process group
                proc_group_children = get_proc_group_children()
                if proc_group_children:
                    psutil.wait_procs(proc_group_children, timeout=1)
                else:
                    # No processes were found in this process group
                    # so we can exit
                    cls._echo('All children are gone. Parent is exiting...\n')
                    exit(0)
            except KeyboardInterrupt:
                # Don't exit immediatedly on Ctrl-C, because we want to
                # wait for the child processes to finish
                cls._echo('\n')
                continue

    def _shutdown(self, message=None, code=0):
        """Shutdown and cleanup everything."""
        if self._shutdown_complete:
            # Make sure we don't accidentally re-run the all cleanup
            exit(code)

        if self.shutdown_callback is not None:
            # Call the shutdown callback with a message suitable for
            # logging and the exit code
            self.shutdown_callback(message, code)

        if self.pid_file is not None:
            self._close_pid_file()

        self._shutdown_complete = True
        exit(code)

    def _handle_terminate(self, signal_number, frame):
        """Handle a signal to terminate."""
        message = 'Terminated by {name} ({number})'.format(
            name=signal_number_to_name(signal_number), number=signal_number)
        self._shutdown(message, code=-signal_number)

    def _forward_signal_to_worker(self, signal_number, frame):
        """Handle a signal by forwarding it to the worker process."""
        pid = None
        if self.pid_file is not None:
            pid = self._read_pid_file()

        self._echo((
            'Received signal {name} ({number}). Forwarding to child...\n'
        ).format(
            name=signal_number_to_name(signal_number),
            number=signal_number,
        ))

        if pid is None:
            # If we can't find the PID of the worker, send the signal to
            # all of this process's children in the process group.
            proc_group_children = get_proc_group_children()
            for proc in proc_group_children:
                os.kill(proc.pid, signal_number)
        else:
            os.kill(pid, signal_number)

    def _run(self, *args, **kwargs):
        """Run the worker function with some custom exception handling."""
        try:
            # Run the worker
            self.worker(*args, **kwargs)
        except SystemExit as ex:
            # exit() was called
            if isinstance(ex.code, int):
                if ex.code is not None and ex.code != 0:
                    # A custom exit code was specified
                    self._shutdown(
                        'Exiting with non-zero exit code {exitcode}'.format(
                            exitcode=ex.code),
                        ex.code)
            else:
                # A message was passed to exit()
                self._shutdown(
                    'Exiting with message: {msg}'.format(msg=ex.code), 1)
        except Exception as ex:
            if self.detach:
                self._shutdown('Dying due to unhandled {cls}: {msg}'.format(
                    cls=ex.__class__.__name__, msg=str(ex)), 1)
            else:
                # We're not detached so just raise the exception
                raise

        self._shutdown('Shutting down normally')

    @expose_action
    def start(self, debug=False, *args, **kwargs):
        """Start the daemon."""
        if self.worker is None:
            raise DaemonError('No worker is defined for daemon')

        if debug:
            self.detach = False

        if os.environ.get('DAEMONOCLE_RELOAD'):
            # If this is actually a reload, we need to wait for the
            # existing daemon to exit first
            self._echo('Reloading {name} ... '.format(name=self.name))
            # Get the parent PID before we orphan this process
            ppid = os.getppid()
            # Orhpan this process so the parent can exit
            self._orphan_this_process(wait_for_parent=True)
            if (ppid is not None and
                    self._pid_is_alive(ppid, timeout=self.stop_timeout)):
                # The process didn't exit for some reason
                self._echo_failed()
                message = ('Previous process (PID {pid}) did NOT '
                           'exit during reload').format(pid=ppid)
                self._echo_error(message)
                self._shutdown(message, 1)

        # Check to see if the daemon is already running
        pid = self._read_pid_file()
        if pid is not None:
            # I don't think this should not be a fatal error
            self._echo_warning('{name} already running with PID {pid}'.format(
                name=self.name, pid=pid))
            return

        if not self.detach and not os.environ.get('DAEMONOCLE_RELOAD'):
            # Setup signal handlers that forward to the worker
            signal.signal(signal.SIGINT, self._forward_signal_to_worker)
            signal.signal(signal.SIGQUIT, self._forward_signal_to_worker)
            signal.signal(signal.SIGTERM, self._forward_signal_to_worker)
            # This keeps the original parent process open so that we
            # maintain control of the tty
            self._fork_and_supervise_child()

        if not os.environ.get('DAEMONOCLE_RELOAD'):
            # A custom message is printed for reloading
            self._echo('Starting {name} ... '.format(name=self.name))

        self._setup_environment()

        if self.detach:
            parent_exitcode = self._detach_process()
            if parent_exitcode is not None:
                return self._maybe_exit(parent_exitcode)

        if self.pid_file is not None:
            self._write_pid_file()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_terminate)
        signal.signal(signal.SIGQUIT, self._handle_terminate)
        signal.signal(signal.SIGTERM, self._handle_terminate)

        if not self.detach:
            self._echo_ok()

        self._run(*args, **kwargs)

    @expose_action
    def stop(self, timeout=None, force=False):
        """Stop the daemon."""
        if self.pid_file is None:
            raise DaemonError('Cannot stop daemon without PID file')

        pid = self._read_pid_file()
        if pid is None:
            # I don't think this should be a fatal error
            self._echo_warning('{name} is not running'.format(name=self.name))
            return 0

        timeout = timeout or self.stop_timeout

        self._echo('Stopping {name} ... '.format(name=self.name))

        try:
            # Try to terminate the process
            os.kill(pid, signal.SIGTERM)
        except OSError as ex:
            self._echo_failed()
            self._echo_error(str(ex))
            return self._maybe_exit(1)

        if not self._pid_is_alive(pid, timeout=timeout):
            self._echo_ok()
            return 0

        # The process didn't terminate for some reason
        self._echo_failed()
        self._echo_error('Timed out while waiting for process (PID {pid}) '
                         'to terminate'.format(pid=pid))

        if force:
            self._echo('Killing {name} ... '.format(name=self.name))
            try:
                # Try to kill the process
                os.kill(pid, signal.SIGKILL)
            except OSError as ex:
                self._echo_failed()
                self._echo_error(str(ex))
                return self._maybe_exit(1)

            if not self._pid_is_alive(pid, timeout=timeout):
                self._echo_ok()
                return 0

            # The process still didn't terminate for some reason
            self._echo_failed()
            self._echo_error('Process (PID {pid}) did not respond to SIGKILL '
                             'for some reason'.format(pid=pid))

        return self._maybe_exit(1)

    @expose_action
    def restart(self, timeout=None, force=False, debug=False, *args, **kwargs):
        """Stop then start the daemon."""
        self.stop(timeout=timeout, force=force)
        self.start(debug=debug, *args, **kwargs)

    def get_status(self, fields=None):
        """Return a dict representing the status of the daemon."""
        if self.pid_file is None:
            raise DaemonError('Cannot get status of daemon without PID file')

        pid = self._read_pid_file()
        if pid is None:
            return {
                'name': self.name,
                'status': psutil.STATUS_DEAD,
            }

        default_fields = {
            'name', 'pid', 'status', 'uptime', 'cpu_percent', 'memory_percent'}
        if fields:
            if isinstance(fields, text):
                fields = {f.strip() for f in fields.split(',')}
            else:
                fields = set(fields)
        else:
            fields = default_fields

        psutil_fields = fields - {'name', 'group_num_procs', 'uptime'}
        if 'uptime' in fields:
            psutil_fields.add('create_time')
        proc_group_info = get_proc_group_info(
            pid,
            fields=psutil_fields)

        status = {}
        for field in fields:
            status[field] = proc_group_info[pid].get(field)

        if 'cpu_percent' in fields:
            status['cpu_percent'] = round(fsum(
                v.get('cpu_percent', 0.0) for v in proc_group_info.values()
            ), 3)
        if 'memory_percent' in fields:
            status['memory_percent'] = round(fsum(
                v.get('memory_percent', 0.0) for v in proc_group_info.values()
            ), 3)

        if 'name' in fields:
            status['name'] = self.name
        if 'group_num_procs' in fields:
            status['group_num_procs'] = len(proc_group_info)
        if 'uptime' in fields:
            status['uptime'] = round(
                time.time() - proc_group_info[pid]['create_time'], 3)

        return status

    @expose_action
    def status(self, json=False, fields=None):
        """Get the status of the daemon."""
        status = self.get_status(fields=fields)
        is_dead = (status.get('status') == psutil.STATUS_DEAD)

        if json:
            message = json_encode(status) + '\n'
        elif is_dead:
            message = '{name} -- not running\n'.format(name=self.name)
        else:
            status['uptime'] = format_elapsed_time(status['uptime'])
            template = (
                '{name} -- pid: {pid}, status: {status}, uptime: {uptime}, '
                '%cpu: {cpu_percent:.1f}, %mem: {memory_percent:.1f}\n')
            message = template.format(**status)

        self._echo(message)

        if is_dead:
            return self._maybe_exit(1)
        else:
            return 0

    @classmethod
    def list_actions(cls):
        """Get a list of exposed actions that are callable via the
        ``do_action()`` method."""
        # Make sure these are always at the beginning of the list
        actions = ['start', 'stop', 'restart', 'status']
        # Iterate over the instance attributes checking for actions that
        # have been exposed
        for func_name in dir(cls):
            func = getattr(cls, func_name)
            if (not callable(func) or
                    not getattr(func, '__daemonocle_exposed__', False)):
                # Not a function or not exposed
                continue
            action = func_name.replace('_', '-')
            if action not in actions:
                actions.append(action)

        return actions

    def get_action(self, action):
        """Get a callable action."""
        func_name = action.replace('-', '_')
        if not hasattr(self, func_name):
            # Function doesn't exist
            raise DaemonError(
                'Invalid action "{action}"'.format(action=action))

        func = getattr(self, func_name)
        if (not callable(func) or
                not getattr(func, '__daemonocle_exposed__', False)):
            # Not a function or not exposed
            raise DaemonError(
                'Invalid action "{action}"'.format(action=action))

        return func

    def do_action(self, action, *args, **kwargs):
        """Call an action by name."""
        func = self.get_action(action)
        return func(*args, **kwargs)

    def cli(self):
        """Invoke the CLI."""
        from daemonocle.cli import DaemonCLI
        cli = DaemonCLI(daemon=self)
        return cli()

    def reload(self):
        """Make the daemon reload itself."""
        pid = self._read_pid_file()
        if pid is None or pid != os.getpid():
            raise DaemonError(
                'Daemon.reload() should only be called by the daemon process '
                'itself')

        # Copy the current environment
        new_environ = os.environ.copy()
        new_environ['DAEMONOCLE_RELOAD'] = 'true'
        # Start a new python process with the same arguments as this one
        subprocess.call(
            [sys.executable] + sys.argv, cwd=self._orig_workdir,
            env=new_environ)
        # Exit this process
        self._shutdown('Shutting down for reload')
