from collections import namedtuple
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap

import psutil
import pytest

from daemonocle import Daemon, DaemonError, expose_action


class _PyFile(object):

    _RunResult = namedtuple(
        'RunResult', ['stdout', 'stderr', 'pid', 'returncode'])

    def __init__(self, code):
        self.dirname = tempfile.mkdtemp(prefix='daemonocle_pytest_')
        self.basename = 'script.py'
        self.realpath = os.path.join(self.dirname, self.basename)
        with open(self.realpath, 'wb') as f:
            f.write(textwrap.dedent(code.lstrip('\n')).encode('utf-8'))

    def run(self, *args):
        proc = subprocess.Popen(
            [sys.executable, self.realpath] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.dirname)
        stdout, stderr = proc.communicate()
        return self._RunResult(stdout, stderr, proc.pid, proc.returncode)

    def teardown(self):
        procs = []
        for proc in psutil.process_iter():
            try:
                if (proc.exe() == sys.executable and
                        self.realpath in proc.cmdline()):
                    proc.terminate()
                    procs.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        gone, alive = psutil.wait_procs(procs, timeout=1)
        if alive:
            raise OSError('Failed to terminate subprocesses')
        shutil.rmtree(self.dirname)


@pytest.fixture(scope='function')
def makepyfile(request):
    pfs = []

    def factory(code):
        pf = _PyFile(code)
        pfs.append(pf)
        return pf

    def teardown():
        for pf in pfs:
            pf.teardown()

    request.addfinalizer(teardown)

    return factory


def test_simple(makepyfile):
    pyfile = makepyfile("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(2)

        daemon = Daemon(worker=worker, prog='foo')
        daemon.do_action(sys.argv[1])
    """)
    result = pyfile.run('start')
    assert result.returncode == 0
    assert result.stdout == b'Starting foo ... OK\n'
    assert result.stderr == b''

    result = pyfile.run('status')
    assert result.returncode == 1
    assert result.stdout == b''
    assert (b'DaemonError: Cannot get status of daemon '
            b'without PID file') in result.stderr

    result = pyfile.run('stop')
    assert result.returncode == 1
    assert result.stdout == b''
    assert b'DaemonError: Cannot stop daemon without PID file' in result.stderr


def test_immediate_exit(makepyfile):
    pyfile = makepyfile("""
        import sys
        from daemonocle import Daemon

        def worker():
            sys.exit(42)

        daemon = Daemon(worker=worker, prog='foo')
        daemon.do_action('start')
    """)
    result = pyfile.run()
    assert result.returncode == 0
    assert result.stdout == b'Starting foo ... FAILED\n'
    assert result.stderr == (b'ERROR: Child exited immediately with '
                             b'exit code 42\n')


def test_non_detached(makepyfile):
    pyfile = makepyfile("""
        import sys
        from daemonocle import Daemon

        def worker():
            print('hello world')
            sys.stdout.flush()

        daemon = Daemon(worker=worker, prog='foo', detach=False)
        daemon.do_action('start')
    """)
    result = pyfile.run()
    assert result.returncode == 0
    assert result.stdout == (
        b'Starting foo ... OK\n'
        b'hello world\n'
        b'All children are gone. Parent is exiting...\n')
    assert result.stderr == b''


def test_pidfile(makepyfile):
    pyfile = makepyfile("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        daemon = Daemon(worker=worker, prog='foo', pidfile='foo.pid')
        daemon.do_action(sys.argv[1])
    """)

    status_pattern = re.compile(
        br'^foo -- pid: (\d+), status: (?:running|sleeping), '
        br'uptime: [0-9mhd ]+, %cpu: \d+\.\d, %mem: \d+\.\d\n$')

    result = pyfile.run('start')
    assert result.returncode == 0
    assert result.stdout == b'Starting foo ... OK\n'
    assert result.stderr == b''

    result = pyfile.run('status')
    assert result.returncode == 0
    match = status_pattern.match(result.stdout)
    assert match
    pid1 = int(match.group(1))
    assert result.stderr == b''

    result = pyfile.run('start')
    assert result.returncode == 0
    assert result.stdout == b''
    assert result.stderr == ('WARNING: foo already running with PID '
                             '{pid}\n'.format(pid=pid1)).encode('utf-8')

    result = pyfile.run('restart')
    assert result.returncode == 0
    assert result.stdout == b'Stopping foo ... OK\nStarting foo ... OK\n'
    assert result.stderr == b''

    result = pyfile.run('status')
    assert result.returncode == 0
    match = status_pattern.match(result.stdout)
    assert match
    pid2 = int(match.group(1))
    assert pid1 != pid2
    assert result.stderr == b''

    result = pyfile.run('stop')
    assert result.returncode == 0
    assert result.stdout == b'Stopping foo ... OK\n'
    assert result.stderr == b''

    result = pyfile.run('status')
    assert result.returncode == 1
    assert result.stdout == b'foo -- not running\n'
    assert result.stderr == b''

    result = pyfile.run('stop')
    assert result.returncode == 0
    assert result.stdout == b''
    assert result.stderr == b'WARNING: foo is not running\n'


def test_piddir(makepyfile):
    pyfile = makepyfile("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        daemon = Daemon(worker=worker, prog='foo', pidfile='foo/foo.pid')
        daemon.do_action(sys.argv[1])
    """)
    piddir = os.path.join(pyfile.dirname, 'foo')
    pyfile.run('start')
    assert os.path.isdir(piddir)
    assert os.listdir(piddir) == ['foo.pid']
    pyfile.run('stop')
    assert os.path.isdir(piddir)
    assert os.listdir(piddir) == []


def test_broken_pidfile(makepyfile):
    pyfile = makepyfile("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        daemon = Daemon(worker=worker, prog='foo', pidfile='foo.pid')
        daemon.do_action(sys.argv[1])
    """)
    pidfile = os.path.realpath(os.path.join(pyfile.dirname, 'foo.pid'))

    pyfile.run('start')

    # Break the PID file
    with open(pidfile, 'wb') as f:
        f.write(b'banana\n')

    result = pyfile.run('status')
    assert result.returncode == 1
    assert result.stdout == b'foo -- not running\n'
    assert result.stderr == ('WARNING: Empty or broken pidfile {pidfile}; '
                             'removing\n').format(
                                pidfile=pidfile).encode('utf8')

    result = pyfile.run('stop')
    assert result.returncode == 0
    assert result.stdout == b''
    assert result.stderr == b'WARNING: foo is not running\n'


def test_stale_pidfile(makepyfile):
    pyfile = makepyfile("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        daemon = Daemon(worker=worker, prog='foo', pidfile='foo.pid')
        daemon.do_action(sys.argv[1])
    """)
    pidfile = os.path.realpath(os.path.join(pyfile.dirname, 'foo.pid'))

    pyfile.run('start')

    with open(pidfile, 'rb') as f:
        pid = int(f.read())

    os.kill(pid, signal.SIGKILL)

    result = pyfile.run('status')
    assert result.returncode == 1
    assert result.stdout == b'foo -- not running\n'
    assert result.stderr == b''

    assert not os.path.isfile(pidfile)

    result = pyfile.run('stop')
    assert result.returncode == 0
    assert result.stdout == b''
    assert result.stderr == b'WARNING: foo is not running\n'


def test_self_reload(makepyfile):
    pyfile = makepyfile("""
        import os
        import sys
        from daemonocle import Daemon

        daemon = Daemon(prog='foo', pidfile='foo.pid', detach=False)

        def worker():
            print('here is my pid: {}'.format(os.getpid()))
            sys.stdout.flush()
            if not os.environ.get('DAEMONOCLE_RELOAD'):
                daemon.reload()

        daemon.worker = worker
        daemon.do_action('start')
    """)
    result = pyfile.run()
    assert result.returncode == 0
    match = re.match((
        br'^Starting foo \.\.\. OK\n'
        br'here is my pid: (\d+)\n'
        br'Reloading foo \.\.\. OK\n'
        br'here is my pid: (\d+)\n'
        br'All children are gone\. Parent is exiting\.\.\.\n$'),
        result.stdout)
    assert match
    assert match.group(1) != match.group(2)
    assert result.stderr == b''

    daemon = Daemon()
    with pytest.raises(DaemonError):
        # Don't allow calling reload like this
        daemon.reload()


def test_default_actions():
    daemon = Daemon()
    assert daemon.list_actions() == ['start', 'stop', 'restart', 'status']
    assert daemon.get_action('start') == daemon.start
    assert daemon.get_action('stop') == daemon.stop
    assert daemon.get_action('restart') == daemon.restart
    assert daemon.get_action('status') == daemon.status
    with pytest.raises(DaemonError):
        daemon.get_action('banana')


def test_custom_actions():
    class BananaDaemon(Daemon):
        @expose_action
        def banana(self):
            pass

        def plantain(self):
            pass

    daemon = BananaDaemon()
    assert daemon.list_actions() == [
        'start', 'stop', 'restart', 'status', 'banana']
    assert daemon.get_action('banana') == daemon.banana
    with pytest.raises(DaemonError):
        daemon.get_action('plantain')


def test_unresponsive_stop(makepyfile):
    pyfile = makepyfile("""
        import signal
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            def handle_sigterm(*args, **kwargs):
                time.sleep(10)

            signal.signal(signal.SIGTERM, handle_sigterm)
            time.sleep(10)

        daemon = Daemon(worker=worker, prog='foo', pidfile='foo.pid',
                        stop_timeout=1)
        daemon.do_action(sys.argv[1])
    """)
    pidfile = os.path.realpath(os.path.join(pyfile.dirname, 'foo.pid'))

    pyfile.run('start')

    with open(pidfile, 'rb') as f:
        pid = int(f.read())

    result = pyfile.run('stop')
    assert result.returncode == 1
    assert result.stdout == b'Stopping foo ... FAILED\n'
    assert result.stderr == ('ERROR: Timed out while waiting for process '
                             '(PID {pid}) to terminate\n').format(
                                pid=pid).encode('utf-8')

    assert psutil.pid_exists(pid)

    os.kill(pid, signal.SIGKILL)

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        pass
    else:
        gone, alive = psutil.wait_procs([proc], timeout=1)
        assert gone and not alive
