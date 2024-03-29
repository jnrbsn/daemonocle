import os
import posixpath
import re
import signal
import sys
import time

import psutil
import pytest

from daemonocle import Daemon, DaemonError


def test_simple(pyscript):
    script = pyscript("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(2)

        daemon = Daemon(worker=worker, name='foo')
        daemon.do_action(sys.argv[1])
    """)
    result = script.run('start')
    assert result.returncode == 0
    assert result.stdout == b'Starting foo ... OK\n'
    assert result.stderr == b''

    result = script.run('status')
    assert result.returncode == 1
    assert result.stdout == b''
    assert (b'DaemonError: Cannot get status of daemon '
            b'without PID file') in result.stderr

    result = script.run('stop')
    assert result.returncode == 1
    assert result.stdout == b''
    assert b'DaemonError: Cannot stop daemon without PID file' in result.stderr


def test_no_args_or_worker():
    daemon = Daemon()
    assert daemon.name == posixpath.basename(sys.argv[0])
    with pytest.raises(DaemonError):
        daemon.do_action('start')


def test_immediate_exit(pyscript):
    script = pyscript("""
        import sys
        from daemonocle import Daemon

        def worker():
            sys.exit(42)

        daemon = Daemon(worker=worker, name='foo')
        daemon.do_action('start')
    """)
    result = script.run()
    assert result.returncode == 42
    assert result.stdout == b'Starting foo ... FAILED\n'
    assert result.stderr == (b'ERROR: Child exited immediately with '
                             b'exit code 42\n')


def test_non_detached(pyscript):
    script = pyscript("""
        from daemonocle import Daemon

        def worker():
            print('hello world')

        daemon = Daemon(worker=worker, name='foo', detach=False)
        daemon.do_action('start')
    """)
    result = script.run()
    assert result.returncode == 0
    assert result.stdout == (
        b'Starting foo ... OK\n'
        b'hello world\n'
        b'All children are gone. Parent is exiting...\n')
    assert result.stderr == b''


def test_non_detached_signal_forwarding_without_pid_file(pyscript):
    script = pyscript("""
        import time
        from daemonocle import Daemon

        def worker():
            print('hello world')
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', detach=False)
        daemon.do_action('start')
    """)
    script.start()
    time.sleep(2)
    os.kill(script.process.pid, signal.SIGTERM)
    result = script.join()

    assert result.returncode == 0
    assert result.stdout == (
        b'Starting foo ... OK\n'
        b'hello world\n'
        b'Received signal SIGTERM (15). Forwarding to child...\n'
        b'All children are gone. Parent is exiting...\n')
    assert result.stderr == b''


def test_non_detached_signal_forwarding_with_pid_file(pyscript):
    script = pyscript("""
        import time
        from daemonocle import Daemon

        def worker():
            print('hello world')
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', detach=False,
                        pid_file='foo.pid')
        daemon.do_action('start')
    """)
    script.start()
    time.sleep(2)
    os.kill(script.process.pid, signal.SIGTERM)
    result = script.join()

    assert result.returncode == 0
    assert result.stdout == (
        b'Starting foo ... OK\n'
        b'hello world\n'
        b'Received signal SIGTERM (15). Forwarding to child...\n'
        b'All children are gone. Parent is exiting...\n')
    assert result.stderr == b''


def test_pidfile(pyscript):
    script = pyscript("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', pid_file='foo.pid')
        daemon.do_action(sys.argv[1])
    """)

    status_pattern = re.compile(
        br'^foo -- pid: (\d+), status: (?:running|sleeping), '
        br'uptime: [0-9mhd ]+, %cpu: \d+\.\d, %mem: \d+\.\d\n$')

    result = script.run('start')
    assert result.returncode == 0
    assert result.stdout == b'Starting foo ... OK\n'
    assert result.stderr == b''

    result = script.run('status')
    assert result.returncode == 0
    match = status_pattern.match(result.stdout)
    assert match
    pid1 = int(match.group(1))
    assert result.stderr == b''

    result = script.run('start')
    assert result.returncode == 0
    assert result.stdout == b''
    assert result.stderr == ('WARNING: foo already running with PID '
                             '{pid}\n'.format(pid=pid1)).encode('utf-8')

    result = script.run('restart')
    assert result.returncode == 0
    assert result.stdout == b'Stopping foo ... OK\nStarting foo ... OK\n'
    assert result.stderr == b''

    result = script.run('status')
    assert result.returncode == 0
    match = status_pattern.match(result.stdout)
    assert match
    pid2 = int(match.group(1))
    assert pid1 != pid2
    assert result.stderr == b''

    result = script.run('stop')
    assert result.returncode == 0
    assert result.stdout == b'Stopping foo ... OK\n'
    assert result.stderr == b''

    result = script.run('status')
    assert result.returncode == 1
    assert result.stdout == b'foo -- not running\n'
    assert result.stderr == b''

    result = script.run('stop')
    assert result.returncode == 0
    assert result.stdout == b''
    assert result.stderr == b'WARNING: foo is not running\n'


def test_piddir(pyscript):
    script = pyscript("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', pid_file='foo/foo.pid')
        daemon.do_action(sys.argv[1])
    """)
    piddir = posixpath.join(script.dirname, 'foo')
    script.run('start')
    assert posixpath.isdir(piddir)
    assert os.listdir(piddir) == ['foo.pid']
    script.run('stop')
    assert posixpath.isdir(piddir)
    assert os.listdir(piddir) == []


def test_broken_pidfile(pyscript):
    script = pyscript("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', pid_file='foo.pid')
        daemon.do_action(sys.argv[1])
    """)
    pid_file = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

    script.run('start')

    # Break the PID file
    with open(pid_file, 'wb') as f:
        f.write(b'banana\n')

    result = script.run('status')
    assert result.returncode == 1
    assert result.stdout == b'foo -- not running\n'
    assert result.stderr == ('WARNING: Empty or broken PID file {pid_file}; '
                             'removing\n').format(
                                pid_file=pid_file).encode('utf8')

    result = script.run('stop')
    assert result.returncode == 0
    assert result.stdout == b''
    assert result.stderr == b'WARNING: foo is not running\n'


def test_stale_pidfile(pyscript):
    script = pyscript("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', pid_file='foo.pid')
        daemon.do_action(sys.argv[1])
    """)
    pid_file = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

    script.run('start')

    with open(pid_file, 'rb') as f:
        pid = int(f.read())

    os.kill(pid, signal.SIGKILL)

    result = script.run('status')
    assert result.returncode == 1
    assert result.stdout == b'foo -- not running\n'
    assert result.stderr == b''

    assert not posixpath.isfile(pid_file)

    result = script.run('stop')
    assert result.returncode == 0
    assert result.stdout == b''
    assert result.stderr == b'WARNING: foo is not running\n'


def test_stdout_and_stderr_file(pyscript):
    script = pyscript("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            sys.stdout.write('1ohhyMgprGBsSgPF7R388fs1VYtF3UyxCzp\\n')
            sys.stdout.flush()
            sys.stderr.write('1PMQcUFXReMo8V4jRK8sRkixpGm6TVb1KJJ\\n')
            sys.stderr.flush()
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', pid_file='foo.pid',
                        stdout_file='stdout.log', stderr_file='stderr.log')
        daemon.do_action(sys.argv[1])
    """)
    pid_file = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

    result = script.run('start')
    try:
        assert result.returncode == 0
        assert result.stdout == b'Starting foo ... OK\n'
        assert result.stderr == b''

        with open(pid_file, 'rb') as f:
            proc = psutil.Process(int(f.read()))

        assert proc.status() in {psutil.STATUS_RUNNING, psutil.STATUS_SLEEPING}

        with open(posixpath.join(script.dirname, 'stdout.log'), 'rb') as f:
            assert f.read() == b'1ohhyMgprGBsSgPF7R388fs1VYtF3UyxCzp\n'
        with open(posixpath.join(script.dirname, 'stderr.log'), 'rb') as f:
            assert f.read() == b'1PMQcUFXReMo8V4jRK8sRkixpGm6TVb1KJJ\n'
    finally:
        result = script.run('stop')
        assert result.returncode == 0
        assert result.stdout == b'Stopping foo ... OK\n'
        assert result.stderr == b''


def test_stdout_and_stderr_file_same_path(pyscript):
    script = pyscript("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            sys.stdout.write('1XPRq1KToN6Wz1y1PeR2dj8BNrnjiPTPaup\\n')
            sys.stdout.flush()
            sys.stderr.write('29qM7pLGqgwwhGAVrWxnce14AsQicSWHnwE\\n')
            sys.stderr.flush()
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', pid_file='foo.pid',
                        stdout_file='output.log', stderr_file='output.log')
        daemon.do_action(sys.argv[1])
    """)
    pid_file = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

    result = script.run('start')
    try:
        assert result.returncode == 0
        assert result.stdout == b'Starting foo ... OK\n'
        assert result.stderr == b''

        with open(pid_file, 'rb') as f:
            proc = psutil.Process(int(f.read()))

        assert proc.status() in {psutil.STATUS_RUNNING, psutil.STATUS_SLEEPING}

        with open(posixpath.join(script.dirname, 'output.log'), 'rb') as f:
            assert f.read() == (
                b'1XPRq1KToN6Wz1y1PeR2dj8BNrnjiPTPaup\n'
                b'29qM7pLGqgwwhGAVrWxnce14AsQicSWHnwE\n')
    finally:
        result = script.run('stop')
        assert result.returncode == 0
        assert result.stdout == b'Stopping foo ... OK\n'
        assert result.stderr == b''


def test_status_uptime(pyscript):
    script = pyscript("""
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', pid_file='foo.pid')

        now = time.time()
        if sys.argv[1] == 'status':
            time.time = lambda: now + int(sys.argv[2])

        daemon.do_action(sys.argv[1])
    """)

    status_pattern = re.compile(
        br'^foo -- pid: \d+, status: (?:running|sleeping), '
        br'uptime: ([0-9mhd ]+), %cpu: \d+\.\d, %mem: \d+\.\d\n$')

    script.run('start')

    result = script.run('status', '0')
    match = status_pattern.match(result.stdout)
    assert match
    assert match.group(1) == b'0m'

    result = script.run('status', '1000')
    match = status_pattern.match(result.stdout)
    assert match
    assert match.group(1) == b'17m'

    result = script.run('status', '10000')
    match = status_pattern.match(result.stdout)
    assert match
    assert match.group(1) == b'2h 47m'

    result = script.run('status', '100000')
    match = status_pattern.match(result.stdout)
    assert match
    assert match.group(1) == b'1d 3h 47m'

    result = script.run('status', '1000000')
    match = status_pattern.match(result.stdout)
    assert match
    assert match.group(1) == b'11d 13h 47m'


def test_self_reload(pyscript):
    script = pyscript("""
        import os
        from daemonocle import Daemon

        daemon = Daemon(name='foo', pid_file='foo.pid', detach=False)

        def worker():
            print('here is my pid: {}'.format(os.getpid()))
            if not os.environ.get('DAEMONOCLE_RELOAD'):
                daemon.reload()

        daemon.worker = worker
        daemon.do_action('start')
    """)
    result = script.run()
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


def test_subclass(pyscript):
    script = pyscript("""
        import daemonocle

        class MyDaemon(daemonocle.Daemon):
            name = '1jizQzV9STeyLTDgL3kiESxnMMRtk9HvGJE'

            def __init__(self):
                super(MyDaemon, self).__init__(detach=False)

            def worker(self):
                print('I am {name}'.format(name=self.name))
                print('also 1ZX5KG8RWZwewPFSgkWhtQiuWfAGTobEtFM')

        if __name__ == '__main__':
            MyDaemon().do_action('start')
    """)
    result = script.run()
    assert result.returncode == 0
    assert result.stdout == (
        b'Starting 1jizQzV9STeyLTDgL3kiESxnMMRtk9HvGJE ... OK\n'
        b'I am 1jizQzV9STeyLTDgL3kiESxnMMRtk9HvGJE\n'
        b'also 1ZX5KG8RWZwewPFSgkWhtQiuWfAGTobEtFM\n'
        b'All children are gone. Parent is exiting...\n')
    assert result.stderr == b''


def test_start_hook(pyscript):
    script = pyscript("""
        from daemonocle import Daemon

        def start_hook(debug):
            print('debug={!r}'.format(debug))
            print('2NJSuZFwJcgHYGWup4xHzFR8MtdTUE3johy')

        def main():
            print('1ZCW56TawPekaVmeQ1GwEg8BgrpPhsvp41s')

        if __name__ == '__main__':
            Daemon(name='foo', worker=main, hooks={'start': start_hook}).cli()
    """)

    result = script.run('start', '--debug')
    assert result.returncode == 0
    assert result.stdout == (
        b'debug=True\n'
        b'2NJSuZFwJcgHYGWup4xHzFR8MtdTUE3johy\n'
        b'Starting foo ... OK\n'
        b'1ZCW56TawPekaVmeQ1GwEg8BgrpPhsvp41s\n'
        b'All children are gone. Parent is exiting...\n')
    assert result.stderr == b''
