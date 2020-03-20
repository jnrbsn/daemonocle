"""Core functionality of daemonocle"""

import errno
import os
import resource
import signal
import socket
import subprocess
import sys
import time

import psutil

from .exceptions import DaemonError


def expose_action(func):
    """This decorator makes a method into an action."""
    func.__daemonocle_exposed__ = True
    return func


class Daemon(object):
    """This is the main class for creating a daemon using daemonocle."""

    def __init__(
            self, worker=None, shutdown_callback=None, prog=None, pidfile=None,
            detach=True, uid=None, gid=None, workdir='/', chrootdir=None,
            umask=0o22, stop_timeout=10, close_open_files=False):
        """Create a new Daemon object."""
        self.worker = worker
        self.shutdown_callback = shutdown_callback
        self.prog = prog if prog is not None else os.path.basename(sys.argv[0])
        self.pidfile = pidfile
        if self.pidfile is not None:
            self.pidfile = os.path.realpath(self.pidfile)
        self.detach = detach & self._is_detach_necessary()
        self.uid = uid if uid is not None else os.getuid()
        self.gid = gid if gid is not None else os.getgid()
        self.workdir = workdir
        self.chrootdir = chrootdir
        self.umask = umask
        self.stop_timeout = stop_timeout
        self.close_open_files = close_open_files

        self._pid_fd = None
        self._shutdown_complete = False
        self._orig_workdir = '/'

    @classmethod
    def _emit_message(cls, message):
        """Print a message to STDOUT."""
        sys.stdout.write(message)
        sys.stdout.flush()

    @classmethod
    def _emit_ok(cls):
        """Print OK for success."""
        cls._emit_message('OK\n')

    @classmethod
    def _emit_failed(cls):
        """Print FAILED on error."""
        cls._emit_message('FAILED\n')

    @classmethod
    def _emit_error(cls, message):
        """Print an error message to STDERR."""
        sys.stderr.write('ERROR: {message}\n'.format(message=message))
        sys.stderr.flush()

    @classmethod
    def _emit_warning(cls, message):
        """Print an warning message to STDERR."""
        sys.stderr.write('WARNING: {message}\n'.format(message=message))
        sys.stderr.flush()

    def _setup_piddir(self):
        """Create the directory for the PID file if necessary."""
        if self.pidfile is None:
            return
        piddir = os.path.dirname(self.pidfile)
        if not os.path.isdir(piddir):
            # Create the directory with sensible mode and ownership
            os.makedirs(piddir, 0o777 & ~self.umask)
            os.chown(piddir, self.uid, self.gid)

    def _read_pidfile(self):
        """Read the PID file and check to make sure it's not stale."""
        if self.pidfile is None:
            return None

        if not os.path.isfile(self.pidfile):
            return None

        # Read the PID file
        with open(self.pidfile, 'r') as fp:
            try:
                pid = int(fp.read())
            except ValueError:
                self._emit_warning('Empty or broken pidfile {pidfile}; '
                                   'removing'.format(pidfile=self.pidfile))
                pid = None

        if pid is not None and psutil.pid_exists(pid):
            return pid
        else:
            # Remove the stale PID file
            os.remove(self.pidfile)
            return None

    def _write_pidfile(self):
        """Create, write to, and lock the PID file."""
        flags = os.O_CREAT | os.O_RDWR
        try:
            # Some systems don't have os.O_EXLOCK
            flags = flags | os.O_EXLOCK
        except AttributeError:
            pass
        self._pid_fd = os.open(self.pidfile, flags, 0o666 & ~self.umask)
        os.write(self._pid_fd, str(os.getpid()).encode('utf-8'))

    def _close_pidfile(self):
        """Closes and removes the PID file."""
        if self._pid_fd is not None:
            os.close(self._pid_fd)
        try:
            os.remove(self.pidfile)
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

        if self.chrootdir is not None:
            try:
                # Change the root directory
                os.chdir(self.chrootdir)
                os.chroot(self.chrootdir)
            except Exception as ex:
                raise DaemonError('Unable to change root directory '
                                  '({error})'.format(error=str(ex)))

        # Prevent the process from generating a core dump
        self._prevent_core_dump()

        try:
            # Switch directories
            os.chdir(self.workdir)
        except Exception as ex:
            raise DaemonError('Unable to change working directory '
                              '({error})'.format(error=str(ex)))

        # Create the directory for the pid file if necessary
        self._setup_piddir()

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

    def _reset_file_descriptors(self):
        """Close open file descriptors and redirect standard streams."""
        if self.close_open_files:
            # Attempt to determine the max number of open files
            max_fds = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
            if max_fds == resource.RLIM_INFINITY:
                # If the limit is infinity, use a more reasonable limit
                max_fds = 2048
        else:
            # If we're not closing all open files, we at least need to
            # reset STDIN, STDOUT, and STDERR.
            max_fds = 3

        for fd in range(max_fds):
            try:
                os.close(fd)
            except OSError:
                # The file descriptor probably wasn't open
                pass

        # Redirect STDIN, STDOUT, and STDERR to /dev/null
        devnull_fd = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull_fd, 0)
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)

    @classmethod
    def _is_socket(cls, stream):
        """Check if the given stream is a socket."""
        try:
            fd = stream.fileno()
        except ValueError:
            # If it has no file descriptor, it's not a socket
            return False

        try:
            # This will raise a socket error on python 3.8 if it's not a
            # socket, see https://bugs.python.org/issue39685
            sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_RAW)

            # This will raise a socket.error if it's not a socket
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
    def _is_detach_necessary(cls):
        """Check if detaching the process is even necessary."""
        if os.getppid() == 1:
            # Process was started by init
            return False

        if cls._is_socket(sys.stdin):
            # If STDIN is a socket, the daemon was started by a super-server
            return False

        return True

    def _detach_process(self):
        """Detach the process via the standard double-fork method with
        some extra magic."""
        # First fork to return control to the shell
        pid = os.fork()
        if pid > 0:
            # Wait for the first child, because it's going to wait and
            # check to make sure the second child is actually running
            # before exiting
            os.waitpid(pid, 0)
            sys.exit(0)

        # Become a process group and session group leader
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
                exitcode = status[1] % 255
                self._emit_failed()
                self._emit_error('Child exited immediately with exit '
                                 'code {code}'.format(code=exitcode))
                sys.exit(exitcode)
            else:
                self._emit_ok()
                sys.exit(0)

        self._reset_file_descriptors()

    @classmethod
    def _orphan_this_process(cls, wait_for_parent=False):
        """Orphan the current process by forking and then waiting for
        the parent to exit."""
        # The current PID will be the PPID of the forked child
        ppid = os.getpid()

        pid = os.fork()
        if pid > 0:
            # Exit parent
            sys.exit(0)

        if wait_for_parent and cls._pid_is_alive(ppid, timeout=1):
            raise DaemonError(
                'Parent did not exit while trying to orphan process')

    @classmethod
    def _fork_and_supervise_child(cls):
        """Fork a child and then watch the process group until there are
        no processes in it."""
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

        # Generate a list of PIDs to exclude when checking for processes
        # in the group (exclude all ancestors that are in the group)
        pgid = os.getpgrp()
        exclude_pids = set([0, os.getpid()])
        proc = psutil.Process()
        while os.getpgid(proc.pid) == pgid:
            exclude_pids.add(proc.pid)
            proc = psutil.Process(proc.ppid())

        while True:
            try:
                # Look for other processes in this process group
                group_procs = []
                for proc in psutil.process_iter():
                    try:
                        if (os.getpgid(proc.pid) == pgid and
                                proc.pid not in exclude_pids):
                            # We found a process in this process group
                            group_procs.append(proc)
                    except (psutil.NoSuchProcess, OSError):
                        continue

                if group_procs:
                    psutil.wait_procs(group_procs, timeout=1)
                else:
                    # No processes were found in this process group
                    # so we can exit
                    cls._emit_message(
                        'All children are gone. Parent is exiting...\n')
                    sys.exit(0)
            except KeyboardInterrupt:
                # Don't exit immediatedly on Ctrl-C, because we want to
                # wait for the child processes to finish
                cls._emit_message('\n')
                continue

    def _shutdown(self, message=None, code=0):
        """Shutdown and cleanup everything."""
        if self._shutdown_complete:
            # Make sure we don't accidentally re-run the all cleanup
            sys.exit(code)

        if self.shutdown_callback is not None:
            # Call the shutdown callback with a message suitable for
            # logging and the exit code
            self.shutdown_callback(message, code)

        if self.pidfile is not None:
            self._close_pidfile()

        self._shutdown_complete = True
        sys.exit(code)

    def _handle_terminate(self, signal_number, _):
        """Handle a signal to terminate."""
        signal_names = {
            signal.SIGINT: 'SIGINT',
            signal.SIGQUIT: 'SIGQUIT',
            signal.SIGTERM: 'SIGTERM',
        }
        message = 'Terminated by {name} ({number})'.format(
            name=signal_names[signal_number], number=signal_number)
        self._shutdown(message, code=128+signal_number)

    def _run(self):
        """Run the worker function with some custom exception handling."""
        try:
            # Run the worker
            self.worker()
        except SystemExit as ex:
            # sys.exit() was called
            if isinstance(ex.code, int):
                if ex.code is not None and ex.code != 0:
                    # A custom exit code was specified
                    self._shutdown(
                        'Exiting with non-zero exit code {exitcode}'.format(
                            exitcode=ex.code),
                        ex.code)
            else:
                # A message was passed to sys.exit()
                self._shutdown(
                    'Exiting with message: {msg}'.format(msg=ex.code), 1)
        except Exception as ex:
            if self.detach:
                self._shutdown('Dying due to unhandled {cls}: {msg}'.format(
                    cls=ex.__class__.__name__, msg=str(ex)), 127)
            else:
                # We're not detached so just raise the exception
                raise

        self._shutdown('Shutting down normally')

    @expose_action
    def start(self):
        """Start the daemon."""
        if self.worker is None:
            raise DaemonError('No worker is defined for daemon')

        if os.environ.get('DAEMONOCLE_RELOAD'):
            # If this is actually a reload, we need to wait for the
            # existing daemon to exit first
            self._emit_message('Reloading {prog} ... '.format(prog=self.prog))
            # Orhpan this process so the parent can exit
            self._orphan_this_process(wait_for_parent=True)
            pid = self._read_pidfile()
            if (pid is not None and
                    self._pid_is_alive(pid, timeout=self.stop_timeout)):
                # The process didn't exit for some reason
                self._emit_failed()
                message = ('Previous process (PID {pid}) did NOT '
                           'exit during reload').format(pid=pid)
                self._emit_error(message)
                self._shutdown(message, 1)

        # Check to see if the daemon is already running
        pid = self._read_pidfile()
        if pid is not None:
            # I don't think this should not be a fatal error
            self._emit_warning('{prog} already running with PID {pid}'.format(
                prog=self.prog, pid=pid))
            return

        if not self.detach and not os.environ.get('DAEMONOCLE_RELOAD'):
            # This keeps the original parent process open so that we
            # maintain control of the tty
            self._fork_and_supervise_child()

        if not os.environ.get('DAEMONOCLE_RELOAD'):
            # A custom message is printed for reloading
            self._emit_message('Starting {prog} ... '.format(prog=self.prog))

        self._setup_environment()

        if self.detach:
            self._detach_process()
        else:
            self._emit_ok()

        if self.pidfile is not None:
            self._write_pidfile()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_terminate)
        signal.signal(signal.SIGQUIT, self._handle_terminate)
        signal.signal(signal.SIGTERM, self._handle_terminate)

        self._run()

    @expose_action
    def stop(self):
        """Stop the daemon."""
        if self.pidfile is None:
            raise DaemonError('Cannot stop daemon without PID file')

        pid = self._read_pidfile()
        if pid is None:
            # I don't think this should be a fatal error
            self._emit_warning('{prog} is not running'.format(prog=self.prog))
            return

        self._emit_message('Stopping {prog} ... '.format(prog=self.prog))

        try:
            # Try to terminate the process
            os.kill(pid, signal.SIGTERM)
        except OSError as ex:
            self._emit_failed()
            self._emit_error(str(ex))
            sys.exit(1)

        if self._pid_is_alive(pid, timeout=self.stop_timeout):
            # The process didn't terminate for some reason
            self._emit_failed()
            self._emit_error('Timed out while waiting for process (PID {pid}) '
                             'to terminate'.format(pid=pid))
            sys.exit(1)

        self._emit_ok()

    @expose_action
    def restart(self):
        """Stop then start the daemon."""
        self.stop()
        self.start()

    @expose_action
    def status(self):
        """Get the status of the daemon."""
        if self.pidfile is None:
            raise DaemonError('Cannot get status of daemon without PID file')

        pid = self._read_pidfile()
        if pid is None:
            self._emit_message(
                '{prog} -- not running\n'.format(prog=self.prog))
            sys.exit(1)

        proc = psutil.Process(pid)
        # Default data
        data = {
            'prog': self.prog,
            'pid': pid,
            'status': proc.status(),
            'uptime': '0m',
            'cpu': 0.0,
            'memory': 0.0,
        }

        # Add up all the CPU and memory usage of all the
        # processes in the process group
        pgid = os.getpgid(pid)
        for gproc in psutil.process_iter():
            try:
                if os.getpgid(gproc.pid) == pgid and gproc.pid != 0:
                    data['cpu'] += gproc.cpu_percent(interval=0.1)
                    data['memory'] += gproc.memory_percent()
            except (psutil.Error, OSError):
                continue

        # Calculate the uptime and format it in a human-readable but
        # also machine-parsable format
        try:
            uptime_mins = int(round((time.time() - proc.create_time()) / 60))
            uptime_hours, uptime_mins = divmod(uptime_mins, 60)
            data['uptime'] = str(uptime_mins) + 'm'
            if uptime_hours:
                uptime_days, uptime_hours = divmod(uptime_hours, 24)
                data['uptime'] = str(uptime_hours) + 'h ' + data['uptime']
                if uptime_days:
                    data['uptime'] = str(uptime_days) + 'd ' + data['uptime']
        except psutil.Error:
            pass

        template = ('{prog} -- pid: {pid}, status: {status}, '
                    'uptime: {uptime}, %cpu: {cpu:.1f}, %mem: {memory:.1f}\n')
        self._emit_message(template.format(**data))

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
            if (not hasattr(func, '__call__') or
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
        if (not hasattr(func, '__call__') or
                getattr(func, '__daemonocle_exposed__', False) is not True):
            # Not a function or not exposed
            raise DaemonError(
                'Invalid action "{action}"'.format(action=action))

        return func

    def do_action(self, action):
        """Call an action by name."""
        func = self.get_action(action)
        func()

    def reload(self):
        """Make the daemon reload itself."""
        pid = self._read_pidfile()
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
