import json
import posixpath


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
