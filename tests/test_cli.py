import re


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
    assert 'No such command' in result.stderr
