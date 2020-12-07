import json
import posixpath
import re
import time

timer = getattr(time, 'monotonic', time.time)


def test_simple(pyscript):
    script = pyscript("""
        import click
        from daemonocle.cli import DaemonCLI

        @click.command(cls=DaemonCLI,
                       daemon_params={'prog': 'foo', 'pidfile': 'foo.pid'})
        def main():
            \"\"\"My awesome daemon\"\"\"
            pass

        if __name__ == '__main__':
            main()
    """)
    result = script.run('--help')
    assert result.returncode == 0
    assert b'My awesome daemon' in result.stdout
    assert re.search((
        br'\s*start\s+Start the daemon\.\n'
        br'\s*stop\s+Stop the daemon\.\n'
        br'\s*restart\s+Stop then start the daemon\.\n'
        br'\s*status\s+Get the status of the daemon\.\n'),
        result.stdout)

    result = script.run('start', '--help')
    assert result.returncode == 0
    assert re.search(
        br'\s*--debug\s+Do NOT detach and run in the background\.\n',
        result.stdout)

    assert script.run('stop', '--help').returncode == 0
    assert script.run('restart', '--help').returncode == 0
    assert script.run('status', '--help').returncode == 0


def test_debug(pyscript):
    script = pyscript("""
        import click
        from daemonocle.cli import DaemonCLI

        @click.command(cls=DaemonCLI, daemon_params={'prog': 'foo'})
        def main():
            \"\"\"My awesome daemon\"\"\"
            print('hello world')

        if __name__ == '__main__':
            main()
    """)
    result = script.run('start', '--debug')
    assert result.returncode == 0
    assert result.stdout == (
        b'Starting foo ... OK\n'
        b'hello world\n'
        b'All children are gone. Parent is exiting...\n')
    assert result.stderr == b''


def test_shorthand_1(pyscript):
    script = pyscript("""
        import click
        from daemonocle.cli import cli

        @cli(prog='foo')
        def main():
            \"\"\"My awesome daemon\"\"\"
            print('hello world')

        if __name__ == '__main__':
            main()
    """)
    result = script.run('start', '--debug')
    assert result.returncode == 0
    assert result.stdout == (
        b'Starting foo ... OK\n'
        b'hello world\n'
        b'All children are gone. Parent is exiting...\n')
    assert result.stderr == b''


def test_shorthand_2(pyscript):
    script = pyscript("""
        from daemonocle import Daemon
        from daemonocle.cli import DaemonCLI

        def main():
            \"\"\"My awesome daemon\"\"\"
            print('hello world')

        if __name__ == '__main__':
            cli = DaemonCLI(daemon=Daemon(prog='foo', worker=main))
            cli()
    """)
    result = script.run('--help')
    assert result.returncode == 0
    assert b'My awesome daemon' in result.stdout

    result = script.run('start', '--debug')
    assert result.returncode == 0
    assert result.stdout == (
        b'Starting foo ... OK\n'
        b'hello world\n'
        b'All children are gone. Parent is exiting...\n')
    assert result.stderr == b''


def test_force_stop(pyscript):
    script = pyscript("""
        import signal
        import sys
        import time
        from daemonocle import Daemon, DaemonCLI

        def worker():
            def handle_sigterm(*args, **kwargs):
                time.sleep(10)

            signal.signal(signal.SIGTERM, handle_sigterm)
            time.sleep(10)

        if __name__ == '__main__':
            cli = DaemonCLI(daemon=Daemon(
                worker=worker, prog='foo', pidfile='foo.pid', stop_timeout=1))
            cli()
    """)
    pidfile = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

    script.run('start')
    with open(pidfile, 'rb') as f:
        pid = int(f.read())
    t1 = timer()
    result = script.run('stop', '--force')
    t2 = timer()
    assert result.returncode == 0
    assert result.stdout == b'Stopping foo ... FAILED\nKilling foo ... OK\n'
    assert result.stderr == ('ERROR: Timed out while waiting for process '
                             '(PID {pid}) to terminate\n').format(
                                pid=pid).encode('utf-8')
    assert 1.0 <= (t2 - t1) <= 1.5


def test_force_stop_custom_timeout(pyscript):
    script = pyscript("""
        import signal
        import sys
        import time
        from daemonocle import Daemon, DaemonCLI

        def worker():
            def handle_sigterm(*args, **kwargs):
                time.sleep(10)

            signal.signal(signal.SIGTERM, handle_sigterm)
            time.sleep(10)

        if __name__ == '__main__':
            cli = DaemonCLI(daemon=Daemon(
                worker=worker, prog='foo', pidfile='foo.pid', stop_timeout=5))
            cli()
    """)
    pidfile = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

    script.run('start')
    with open(pidfile, 'rb') as f:
        pid = int(f.read())
    t1 = timer()
    result = script.run('stop', '--force', '--timeout=1')
    t2 = timer()
    assert result.returncode == 0
    assert result.stdout == b'Stopping foo ... FAILED\nKilling foo ... OK\n'
    assert result.stderr == ('ERROR: Timed out while waiting for process '
                             '(PID {pid}) to terminate\n').format(
                                pid=pid).encode('utf-8')
    assert 1.0 <= (t2 - t1) <= 1.5


def test_status_json(pyscript):
    script = pyscript("""
        import time
        from daemonocle.cli import cli

        @cli(prog='foo', pidfile='foo.pid')
        def main():
            time.sleep(10)

        if __name__ == '__main__':
            main()
    """)
    pidfile = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

    script.run('start')
    with open(pidfile, 'rb') as f:
        pid = int(f.read())

    result = script.run('status', '--json')
    assert result.returncode == 0
    status = json.loads(result.stdout.decode('ascii').rstrip('\n'))
    assert status['prog'] == 'foo'
    assert status['pid'] == pid
    assert status['status'] in {'running', 'sleeping'}
    assert isinstance(status['uptime'], float)
    assert isinstance(status['cpu_percent'], float)
    assert isinstance(status['memory_percent'], float)

    script.run('stop')

    result = script.run('status', '--json')
    assert result.returncode == 1
    status = json.loads(result.stdout.decode('ascii').rstrip('\n'))
    assert status['prog'] == 'foo'
    assert status['status'] == 'dead'


def test_status_fields(pyscript):
    script = pyscript("""
        import subprocess
        from daemonocle.cli import cli

        @cli(prog='foo', pidfile='foo.pid')
        def main():
            subprocess.check_call(['sleep', '10'])

        if __name__ == '__main__':
            main()
    """)
    pidfile = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

    script.run('start')
    result = script.run(
        'status', '--json', '--fields=group_num_procs,open_files')
    assert result.returncode == 0
    status = json.loads(result.stdout.decode('ascii').rstrip('\n'))
    assert status['group_num_procs'] == 2
    open_file_paths = set()
    for item in status['open_files']:
        try:
            path = posixpath.realpath(item[0])
        except OSError:
            continue
        else:
            open_file_paths.add(path)
    assert pidfile in open_file_paths

    script.run('stop')


def test_custom_actions(pyscript):
    script = pyscript("""
        import time
        import click
        from daemonocle import Daemon, expose_action
        from daemonocle.cli import DaemonCLI

        class BananaDaemon(Daemon):
            @expose_action
            def banana(self):
                \"\"\"Go bananas.\"\"\"
                pass

            def plantain(self):
                pass

        @click.command(cls=DaemonCLI, daemon_class=BananaDaemon,
                       daemon_params={'prog': 'foo', 'pidfile': 'foo.pid'})
        def main():
            \"\"\"The banana daemon\"\"\"
            pass

        if __name__ == '__main__':
            main()
    """)
    result = script.run('--help')
    assert result.returncode == 0
    assert b'The banana daemon' in result.stdout
    assert re.search(br'\s*banana\s+Go bananas\.\n', result.stdout)

    assert script.run('banana', '--help').returncode == 0

    result = script.run('plantain', '--help')
    assert result.returncode != 0
    assert b'No such command' in result.stderr
