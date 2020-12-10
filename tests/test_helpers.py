import json
import os
import posixpath
from hashlib import sha256

import psutil
import pytest

from daemonocle.helpers import FHSDaemon


@pytest.mark.skipif(not psutil.LINUX, reason='Only run on Linux')
@pytest.mark.sudo
@pytest.mark.parametrize(
    ('prefix', 'pidfile', 'stdout_file', 'stderr_file', 'cleanup_dirs'),
    (
        (
            '/opt',
            '/var/opt/{prog}/run/{prog}.pid',
            '/var/opt/{prog}/log/stdout.log',
            '/var/opt/{prog}/log/stderr.log',
            ('/var/opt/{prog}',),
        ),
        (
            '/usr/local',
            '/var/local/run/{prog}/{prog}.pid',
            '/var/local/log/{prog}/stdout.log',
            '/var/local/log/{prog}/stderr.log',
            ('/var/local/run/{prog}', '/var/local/log/{prog}'),
        ),
        (
            '/usr',
            '/var/run/{prog}/{prog}.pid',
            '/var/log/{prog}/stdout.log',
            '/var/log/{prog}/stderr.log',
            ('/var/run/{prog}', '/var/log/{prog}'),
        ),
        (
            '/tmp/{prog}',
            '/tmp/{prog}/run/{prog}.pid',
            '/tmp/{prog}/log/stdout.log',
            '/tmp/{prog}/log/stderr.log',
            ('/tmp/{prog}',),
        ),
    )
)
def test_fhs_daemon(
        pyscript, prefix, pidfile, stdout_file, stderr_file, cleanup_dirs):
    prog = sha256(os.urandom(1024)).hexdigest()

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
            prog='{prog}',
            prefix='{prefix}',
            worker=worker,
        ).cli()
    """.format(
        prog=prog,
        prefix=prefix.format(prog=prog),
    ))

    try:
        result = script.run('start')
        assert result.returncode == 0
        assert result.stdout.decode('ascii') == (
            'Starting {prog} ... OK\n'.format(prog=prog))
        assert result.stderr == b''

        with open(pidfile.format(prog=prog), 'rb') as f:
            pid = int(f.read())

        result = script.run('status', '--json', '--fields=prog,pid,status')
        assert result.returncode == 0
        status = json.loads(result.stdout.decode('ascii').rstrip('\n'))
        assert status['prog'] == prog
        assert status['pid'] == pid
        assert status['status'] in {'running', 'sleeping'}

        result = script.run('stop')
        assert result.returncode == 0
        assert result.stdout.decode('ascii') == (
            'Stopping {prog} ... OK\n'.format(prog=prog))
        assert result.stderr == b''

        with open(stdout_file.format(prog=prog), 'rb') as f:
            assert f.read() == b'1MUXMD4fhoF8JJbCVvoy64rtXdnBNQecYHU\n'
        with open(stderr_file.format(prog=prog), 'rb') as f:
            assert f.read() == b'2ffzKqhoVM75joucXzHFsjjCJ5vCBZCz7Ky\n'
    finally:
        # This needs to run with the same permissions as the original script
        cleanup_script = pyscript("""
            import shutil, sys
            shutil.rmtree(sys.argv[1])
        """)
        for cleanup_dir in cleanup_dirs:
            result = cleanup_script.run(cleanup_dir.format(prog=prog))
            assert result.returncode == 0


def test_fhs_daemon_no_prog():
    with pytest.raises(ValueError) as exc_info:
        FHSDaemon()
    assert str(exc_info.value) == 'prog must be defined for FHSDaemon'


def test_exec_worker(pyscript):
    script = pyscript("""
        from daemonocle import Daemon
        from daemonocle.helpers import ExecWorker

        Daemon(
            prog='hello_world',
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
            prog='goodnight_world',
            worker=ExecWorker(b'sleep', b'10'),
            pidfile='goodnight_world.pid',
        ).cli()
    """)
    pidfile = posixpath.realpath(posixpath.join(
        script.dirname, 'goodnight_world.pid'))

    result = script.run('start')
    assert result.returncode == 0
    assert result.stdout == b'Starting goodnight_world ... OK\n'
    assert result.stderr == b''

    with open(pidfile, 'rb') as f:
        pid = int(f.read())

    result = script.run('status', '--json')
    assert result.returncode == 0
    status = json.loads(result.stdout.decode('ascii').rstrip('\n'))
    assert status['prog'] == 'goodnight_world'
    assert status['pid'] == pid
    assert status['status'] in {'running', 'sleeping'}
    assert isinstance(status['uptime'], float)
    assert isinstance(status['cpu_percent'], float)
    assert isinstance(status['memory_percent'], float)

    result = script.run('stop')
    assert result.returncode == 0
    assert result.stdout == b'Stopping goodnight_world ... OK\n'
    assert result.stderr == b''
