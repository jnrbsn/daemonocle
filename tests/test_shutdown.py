import os
import re
import signal

import psutil


def test_sys_exit_message(pyscript):
    script = pyscript("""
        import os
        import sys
        import time
        from daemonocle import Daemon

        orig_dir = os.getcwd()

        def worker():
            time.sleep(2)
            sys.exit('goodbye world')

        def shutdown_callback(message, returncode):
            with open(os.path.join(orig_dir, 'foo.log'), 'w') as f:
                f.write(message)

        daemon = Daemon(worker=worker, prog='foo', pidfile='foo.pid',
                        shutdown_callback=shutdown_callback)
        daemon.do_action('start')
    """)
    script.run()

    with open(os.path.join(script.dirname, 'foo.pid'), 'rb') as f:
        pid = int(f.read())

    psutil.Process(pid).wait()

    with open(os.path.join(script.dirname, 'foo.log'), 'r') as f:
        assert f.read() == 'Exiting with message: goodbye world'


def test_uncaught_exception(pyscript):
    script = pyscript("""
        import os
        import time
        from daemonocle import Daemon

        orig_dir = os.getcwd()

        def worker():
            time.sleep(2)
            raise ValueError('banana')

        def shutdown_callback(message, returncode):
            with open(os.path.join(orig_dir, 'foo.log'), 'w') as f:
                f.write(message)

        daemon = Daemon(worker=worker, prog='foo', pidfile='foo.pid',
                        shutdown_callback=shutdown_callback)
        daemon.do_action('start')
    """)
    script.run()

    with open(os.path.join(script.dirname, 'foo.pid'), 'rb') as f:
        pid = int(f.read())

    psutil.Process(pid).wait()

    with open(os.path.join(script.dirname, 'foo.log'), 'r') as f:
        assert f.read() == 'Dying due to unhandled ValueError: banana'

    script = pyscript("""
        from daemonocle import Daemon

        def worker():
            raise ValueError('banana')

        daemon = Daemon(worker=worker, prog='foo', detach=False)
        daemon.do_action('start')
    """)
    result = script.run()
    assert result.stderr.endswith(b'\nValueError: banana\n')


def test_unresponsive_stop(pyscript):
    script = pyscript("""
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
    pidfile = os.path.realpath(os.path.join(script.dirname, 'foo.pid'))

    script.run('start')

    with open(pidfile, 'rb') as f:
        pid = int(f.read())

    result = script.run('stop')
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
        proc.wait(timeout=1)


def test_unresponsive_reload(pyscript):
    script = pyscript("""
        import os
        import time
        from daemonocle import Daemon

        def worker():
            print('here is my pid: {}'.format(os.getpid()))
            daemon.reload()

        def shutdown_callback(message, returncode):
            if not os.environ.get('DAEMONOCLE_RELOAD'):
                time.sleep(2)

        daemon = Daemon(worker=worker, shutdown_callback=shutdown_callback,
                        prog='foo', pidfile='foo.pid', detach=False,
                        stop_timeout=1)

        daemon.do_action('start')
    """)
    result = script.run()

    match = re.match((
        br'^Starting foo \.\.\. OK\n'
        br'here is my pid: (\d+)\n'
        br'Reloading foo \.\.\. FAILED\n'
        br'All children are gone\. Parent is exiting\.\.\.\n$'),
        result.stdout)
    assert match
    pid1 = match.group(1)

    match = re.match((
        br'ERROR: Previous process \(PID (\d+)\) '
        br'did NOT exit during reload\n$'),
        result.stderr)
    assert match
    pid2 = match.group(1)

    assert pid1 == pid2
