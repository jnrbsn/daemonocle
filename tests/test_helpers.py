import json
import os
import posixpath
from hashlib import sha256

import psutil
import pytest

from daemonocle import DaemonError
from daemonocle.helpers import FHSDaemon


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
