import json
import os
import posixpath
from hashlib import sha256

import psutil
import pytest

from daemonocle import DaemonError
from daemonocle.helpers import FHSDaemon, MultiDaemon


@pytest.mark.skipif(not psutil.LINUX, reason='only run on Linux')
@pytest.mark.sudo
@pytest.mark.parametrize(
    ('prefix', 'pid_file', 'stdout_file', 'stderr_file', 'cleanup_dirs'),
    (
        (
            '/opt',
            '/var/opt/{name}/run/{name}.pid',
            '/var/opt/{name}/log/out.log',
            '/var/opt/{name}/log/err.log',
            ('/var/opt/{name}',),
        ),
        (
            '/usr/local',
            '/var/local/run/{name}/{name}.pid',
            '/var/local/log/{name}/out.log',
            '/var/local/log/{name}/err.log',
            ('/var/local/run/{name}', '/var/local/log/{name}'),
        ),
        (
            '/usr',
            '/var/run/{name}/{name}.pid',
            '/var/log/{name}/out.log',
            '/var/log/{name}/err.log',
            ('/var/run/{name}', '/var/log/{name}'),
        ),
        (
            '/tmp/{name}',
            '/tmp/{name}/run/{name}.pid',
            '/tmp/{name}/log/out.log',
            '/tmp/{name}/log/err.log',
            ('/tmp/{name}',),
        ),
    )
)
def test_fhs_daemon(
        pyscript, prefix, pid_file, stdout_file, stderr_file, cleanup_dirs):
    name = sha256(os.urandom(1024)).hexdigest()

    script = pyscript("""
        import sys
        import time
        from daemonocle.helpers import FHSDaemon

        def worker():
            sys.stdout.write('1MUXMD4fhoF8JJbCVvoy64rtXdnBNQecYHU\\n')
            sys.stdout.flush()
            sys.stderr.write('2ffzKqhoVM75joucXzHFsjjCJ5vCBZCz7Ky\\n')
            sys.stderr.flush()
            time.sleep(10)

        FHSDaemon(
            name='{name}',
            prefix='{prefix}',
            worker=worker,
        ).cli()
    """.format(
        name=name,
        prefix=prefix.format(name=name),
    ))

    try:
        result = script.run('start')
        assert result.returncode == 0
        assert result.stdout.decode('ascii') == (
            'Starting {name} ... OK\n'.format(name=name))
        assert result.stderr == b''

        with open(pid_file.format(name=name), 'rb') as f:
            pid = int(f.read())

        result = script.run('status', '--json', '--fields=name,pid,status')
        assert result.returncode == 0
        status = json.loads(result.stdout.decode('ascii').rstrip('\n'))
        assert status['name'] == name
        assert status['pid'] == pid
        assert status['status'] in {'running', 'sleeping'}

        result = script.run('stop')
        assert result.returncode == 0
        assert result.stdout.decode('ascii') == (
            'Stopping {name} ... OK\n'.format(name=name))
        assert result.stderr == b''

        with open(stdout_file.format(name=name), 'rb') as f:
            assert f.read() == b'1MUXMD4fhoF8JJbCVvoy64rtXdnBNQecYHU\n'
        with open(stderr_file.format(name=name), 'rb') as f:
            assert f.read() == b'2ffzKqhoVM75joucXzHFsjjCJ5vCBZCz7Ky\n'
    finally:
        # This needs to run with the same permissions as the original script
        cleanup_script = pyscript("""
            import shutil, sys
            shutil.rmtree(sys.argv[1])
        """)
        for cleanup_dir in cleanup_dirs:
            cleanup_dir = cleanup_dir.format(name=name)
            assert cleanup_dir != '/'  # Safety check
            result = cleanup_script.run(cleanup_dir)
            assert result.returncode == 0


def test_fhs_daemon_no_prog():
    with pytest.raises(DaemonError) as exc_info:
        FHSDaemon()
    assert str(exc_info.value) == 'name must be defined for FHSDaemon'


def test_multi_daemon(pyscript):
    script = pyscript("""
        import sys
        import time
        from daemonocle.helpers import FHSDaemon, MultiDaemon

        def worker():
            sys.stdout.write('14AAwNxSJCYnZck4zHDavK38J1hPCNo5ZjG\\n')
            sys.stdout.flush()
            sys.stderr.write('27rUarEY9XRHap294GZ5s3B2oc248XcFuSQ\\n')
            sys.stderr.flush()
            time.sleep(60)

        MultiDaemon(
            name='foo_worker_{n:0>4}',
            worker=worker,
            prefix='foo/{n:0>4}',
            num_workers=4,
            daemon_cls=FHSDaemon,
        ).cli()
    """)

    result = script.run('start')
    try:
        assert result.returncode == 0
        assert result.stdout == (
            b'Starting foo_worker_0000 ... OK\n'
            b'Starting foo_worker_0001 ... OK\n'
            b'Starting foo_worker_0002 ... OK\n'
            b'Starting foo_worker_0003 ... OK\n')
        assert result.stderr == b''

        pids = []
        sids = set()
        pgids = set()
        for n in range(4):
            pid_file = posixpath.join(
                script.dirname,
                'foo/{n:0>4}/run/foo_worker_{n:0>4}.pid'.format(n=n))
            with open(pid_file, 'rb') as f:
                pid = int(f.read())
            pids.append(pid)

            sids.add(os.getsid(pid))
            pgids.add(os.getpgid(pid))

            stdout_file = posixpath.join(
                script.dirname, 'foo/{n:0>4}/log/out.log'.format(n=n))
            with open(stdout_file, 'rb') as f:
                assert f.read() == b'14AAwNxSJCYnZck4zHDavK38J1hPCNo5ZjG\n'

            stderr_file = posixpath.join(
                script.dirname, 'foo/{n:0>4}/log/err.log'.format(n=n))
            with open(stderr_file, 'rb') as f:
                assert f.read() == b'27rUarEY9XRHap294GZ5s3B2oc248XcFuSQ\n'

        # They should all be in the same session
        assert len(sids) == 1
        # They should all be leaders of different process groups
        assert len(pgids) == 4
        assert set(pids) == pgids

        result = script.run('status', '--json')
        assert result.returncode == 0
        statuses = json.loads(result.stdout.decode('ascii').rstrip('\n'))
        for n, status in enumerate(statuses):
            assert status['pid'] == pids[n]
            assert status['name'] == 'foo_worker_{n:0>4}'.format(n=n)

        # Try to create a large amount of status data
        result = script.run(
            'status', '--json',
            '--fields=pid,name,cpu_times,cwd,environ,io_counters,open_files')
        assert result.returncode == 0
        statuses = json.loads(result.stdout.decode('ascii').rstrip('\n'))
        for n, status in enumerate(statuses):
            assert status['pid'] == pids[n]
            assert status['name'] == 'foo_worker_{n:0>4}'.format(n=n)

        result = script.run('status')
        assert result.returncode == 0
        for n, line in enumerate(result.stdout.splitlines()):
            line = line.decode('ascii')
            assert line.startswith(
                'foo_worker_{n:0>4} -- pid: {pid}, '.format(n=n, pid=pids[n]))
    finally:
        result = script.run('stop')
        assert result.returncode == 0
        assert result.stdout == (
            b'Stopping foo_worker_0000 ... OK\n'
            b'Stopping foo_worker_0001 ... OK\n'
            b'Stopping foo_worker_0002 ... OK\n'
            b'Stopping foo_worker_0003 ... OK\n')
        assert result.stderr == b''

        result = script.run('status')
        assert result.returncode == 0
        assert result.stdout == (
            b'foo_worker_0000 -- not running\n'
            b'foo_worker_0001 -- not running\n'
            b'foo_worker_0002 -- not running\n'
            b'foo_worker_0003 -- not running\n')
        assert result.stderr == b''


def test_multi_daemon_basic(pyscript):
    script = pyscript("""
        import time
        from daemonocle.helpers import MultiDaemon

        def worker():
            time.sleep(10)

        MultiDaemon(
            name='foo_{n}',
            worker=worker,
            pid_file='foo.{n}.pid',
            num_workers=2,
        ).cli()
    """)

    result = script.run('start')
    try:
        assert result.returncode == 0
        assert result.stdout == (
            b'Starting foo_0 ... OK\n'
            b'Starting foo_1 ... OK\n')
        assert result.stderr == b''
    finally:
        result = script.run('stop')
        assert result.returncode == 0
        assert result.stdout == (
            b'Stopping foo_0 ... OK\n'
            b'Stopping foo_1 ... OK\n')
        assert result.stderr == b''


def test_multi_daemon_error_no_pid_file():
    with pytest.raises(DaemonError) as exc_info:
        MultiDaemon(num_workers=2, worker=lambda: None)
    assert str(exc_info.value) == 'pid_file must be defined for MultiDaemon'


def test_multi_daemon_error_non_unique_pid_files():
    with pytest.raises(DaemonError) as exc_info:
        MultiDaemon(num_workers=2, worker=lambda: None, pid_file='foo.pid')
    assert str(exc_info.value) == 'PID files must be unique for MultiDaemon'


def test_multi_daemon_error_invalid_action():
    multi_daemon = MultiDaemon(
        num_workers=2, worker=lambda: None, pid_file='foo.{n}.pid')
    with pytest.raises(DaemonError) as exc_info:
        multi_daemon.do_action('banana')
    assert str(exc_info.value) == 'Invalid action "banana"'


def test_exec_worker(pyscript):
    script = pyscript("""
        from daemonocle import Daemon
        from daemonocle.helpers import ExecWorker

        Daemon(
            name='hello_world',
            worker=ExecWorker('/bin/echo', 'hello world'),
            detach=False,
        ).cli()
    """)
    result = script.run('start')
    assert result.returncode == 0
    assert result.stdout == (
        b'Starting hello_world ... OK\n'
        b'hello world\n'
        b'All children are gone. Parent is exiting...\n')
    assert result.stderr == b''


def test_exec_worker_detached(pyscript):
    script = pyscript("""
        from daemonocle import Daemon
        from daemonocle.helpers import ExecWorker

        Daemon(
            name='goodnight_world',
            worker=ExecWorker(b'sleep', b'10'),
            pid_file='goodnight_world.pid',
        ).cli()
    """)
    pid_file = posixpath.realpath(posixpath.join(
        script.dirname, 'goodnight_world.pid'))

    result = script.run('start')
    assert result.returncode == 0
    assert result.stdout == b'Starting goodnight_world ... OK\n'
    assert result.stderr == b''

    with open(pid_file, 'rb') as f:
        pid = int(f.read())

    result = script.run('status', '--json')
    assert result.returncode == 0
    status = json.loads(result.stdout.decode('ascii').rstrip('\n'))
    assert status['name'] == 'goodnight_world'
    assert status['pid'] == pid
    assert status['status'] in {'running', 'sleeping'}
    assert isinstance(status['uptime'], float)
    assert isinstance(status['cpu_percent'], float)
    assert isinstance(status['memory_percent'], float)

    result = script.run('stop')
    assert result.returncode == 0
    assert result.stdout == b'Stopping goodnight_world ... OK\n'
    assert result.stderr == b''
