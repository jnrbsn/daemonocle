import json
import posixpath
import re
import sys
import time

import pytest

timer = getattr(time, 'monotonic', time.time)


def test_simple(pyscript):
    script = pyscript("""
        import click
        from daemonocle.cli import DaemonCLI

        @click.command(cls=DaemonCLI,
                       daemon_params={'name': 'foo', 'pid_file': 'foo.pid'})
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

        @click.command(cls=DaemonCLI, daemon_params={'name': 'foo'})
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

        @cli(name='foo')
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
            cli = DaemonCLI(daemon=Daemon(name='foo', worker=main))
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
                worker=worker, name='foo', pid_file='foo.pid', stop_timeout=1))
            cli()
    """)
    pid_file = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

    script.run('start')
    with open(pid_file, 'rb') as f:
        pid = int(f.read())
    t1 = timer()
    result = script.run('stop', '--force')
    t2 = timer()
    assert result.returncode == 0
    assert result.stdout == b'Stopping foo ... FAILED\nKilling foo ... OK\n'
    assert result.stderr == ('ERROR: Timed out while waiting for process '
                             '(PID {pid}) to terminate\n').format(
                                pid=pid).encode('utf-8')
    assert 1.0 <= (t2 - t1) < 2.0


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
                worker=worker, name='foo', pid_file='foo.pid', stop_timeout=5))
            cli()
    """)
    pid_file = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

    script.run('start')
    with open(pid_file, 'rb') as f:
        pid = int(f.read())
    t1 = timer()
    result = script.run('stop', '--force', '--timeout=1')
    t2 = timer()
    assert result.returncode == 0
    assert result.stdout == b'Stopping foo ... FAILED\nKilling foo ... OK\n'
    assert result.stderr == ('ERROR: Timed out while waiting for process '
                             '(PID {pid}) to terminate\n').format(
                                pid=pid).encode('utf-8')
    assert 1.0 <= (t2 - t1) < 2.0


def test_status_json(pyscript):
    script = pyscript("""
        import time
        from daemonocle.cli import cli

        @cli(name='foo', pid_file='foo.pid')
        def main():
            time.sleep(10)

        if __name__ == '__main__':
            main()
    """)
    pid_file = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

    script.run('start')
    with open(pid_file, 'rb') as f:
        pid = int(f.read())

    result = script.run('status', '--json')
    assert result.returncode == 0
    status = json.loads(result.stdout.decode('ascii').rstrip('\n'))
    assert status['name'] == 'foo'
    assert status['pid'] == pid
    assert status['status'] in {'running', 'sleeping'}
    assert isinstance(status['uptime'], float)
    assert isinstance(status['cpu_percent'], float)
    assert isinstance(status['memory_percent'], float)

    script.run('stop')

    result = script.run('status', '--json')
    assert result.returncode == 1
    status = json.loads(result.stdout.decode('ascii').rstrip('\n'))
    assert status['name'] == 'foo'
    assert status['status'] == 'dead'


def test_status_fields(pyscript):
    script = pyscript("""
        import subprocess
        from daemonocle.cli import cli

        @cli(name='foo', pid_file='foo.pid')
        def main():
            subprocess.check_call(['sleep', '10'])

        if __name__ == '__main__':
            main()
    """)
    pid_file = posixpath.realpath(posixpath.join(script.dirname, 'foo.pid'))

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
    assert pid_file in open_file_paths

    script.run('stop')


def test_custom_actions(pyscript):
    script = pyscript("""
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
                       daemon_params={'name': 'foo', 'pid_file': 'foo.pid'})
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


@pytest.mark.skipif(sys.version_info.major < 3, reason='Requires Python 3.x')
def test_custom_actions_with_options(pyscript):
    script = pyscript("""
        import daemonocle

        class MyDaemon(daemonocle.Daemon):
            name = 'my_daemon'

            @daemonocle.expose_action
            def foo(self, wibble: int,
                    wobble: str = '1ErrJ5QgasJKkcMdRBrEQHtyGqkWLa1sSJS'):
                \"\"\"2ScD2S4w44jivwVNAamYdCVUU8afdDqTsGU\"\"\"
                print(wibble * 24369)
                print(sum(map(ord, wobble)))

            @daemonocle.expose_action
            def bar(self, wubble=False, flub=True, **kwargs):
                \"\"\"1R3YQRaAMU2inZ7mhtZC96MTiaykPYGCqC9\"\"\"
                print(repr(wubble))
                print(repr(flub))
                print(repr(kwargs))

            def worker(self):
                \"\"\"2PfZ4gSZaghZXK3VuDqbD82ZGqpqDLAKPpj\"\"\"
                pass

        if __name__ == '__main__':
            MyDaemon(pid_file='foo.pid').cli()
    """)
    result = script.run('--help')
    assert result.returncode == 0
    assert b'2PfZ4gSZaghZXK3VuDqbD82ZGqpqDLAKPpj' in result.stdout
    assert re.search(
        br'\s*foo\s+2ScD2S4w44jivwVNAamYdCVUU8afdDqTsGU\n', result.stdout)
    assert re.search(
        br'\s*bar\s+1R3YQRaAMU2inZ7mhtZC96MTiaykPYGCqC9\n', result.stdout)

    result = script.run('foo', '--help')
    assert result.returncode == 0
    assert b'2ScD2S4w44jivwVNAamYdCVUU8afdDqTsGU' in result.stdout
    assert b'--wibble' in result.stdout
    assert b'--wobble' in result.stdout

    result = script.run('foo')
    assert result.returncode == 2
    assert b'Missing option \'--wibble\'' in result.stderr

    result = script.run('foo', '--wibble=9055')
    assert result.returncode == 0
    assert result.stdout == b'220661295\n3077\n'

    result = script.run('foo', '--wibble=1850',
                        '--wobble=26hevLhGzeeX7dNqAtdXjKBtmevsxgBvWNG')
    assert result.returncode == 0
    assert result.stdout == b'45082650\n3254\n'

    result = script.run('bar')
    assert result.returncode == 0
    assert result.stdout == b'False\nTrue\n{}\n'

    result = script.run('bar', '--flub')
    assert result.returncode == 0
    assert result.stdout == b'False\nTrue\n{}\n'

    result = script.run('bar', '--wubble', '--no-flub')
    assert result.returncode == 0
    assert result.stdout == b'True\nFalse\n{}\n'
