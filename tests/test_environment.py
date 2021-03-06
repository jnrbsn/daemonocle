import os
import posixpath
from pwd import getpwnam

import psutil
import pytest

from daemonocle import Daemon, DaemonEnvironmentError, DaemonError
from daemonocle._utils import proc_get_open_fds


def test_reset_file_descriptors(pyscript):
    script = pyscript("""
        import os
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        open_file = open('foo.txt', 'w+')
        close_files = bool(int(sys.argv[2])) if len(sys.argv) > 2 else False
        daemon = Daemon(worker=worker, name='foo', pid_file='foo.pid',
                        work_dir=os.getcwd(),
                        close_open_files=close_files)
        daemon.do_action(sys.argv[1])
    """)
    pid_file = posixpath.join(script.dirname, 'foo.pid')

    script.run('start', '0')

    with open(pid_file, 'rb') as f:
        proc = psutil.Process(int(f.read()))

    assert len(proc_get_open_fds(proc.pid)) >= 4
    open_files = {posixpath.relpath(x.path, script.dirname)
                  for x in proc.open_files()}
    assert open_files == {'foo.txt', 'foo.pid'}

    script.run('restart', '1')

    with open(pid_file, 'rb') as f:
        proc = psutil.Process(int(f.read()))

    assert len(proc_get_open_fds(proc.pid)) == 4
    open_files = {posixpath.relpath(x.path, script.dirname)
                  for x in proc.open_files()}
    assert open_files == {'foo.pid'}

    script.run('stop')


def test_chrootdir_without_permission():
    daemon = Daemon(worker=lambda: None, chroot_dir=os.getcwd())
    with pytest.raises(DaemonError) as exc_info:
        daemon.do_action('start')
    assert ('Unable to change root directory '
            '([Errno 1] Operation not permitted') in str(exc_info.value)


@pytest.mark.sudo
def test_chrootdir(pyscript):
    script = pyscript("""
        import os
        import sys
        from daemonocle import Daemon

        def worker():
            with open('/banana', 'r') as f:
                sys.stderr.write(f.read() + '\\n')

        daemon = Daemon(worker=worker, name='foo', detach=False,
                        chroot_dir=os.path.join(os.getcwd(), 'foo'))
        daemon.do_action('start')
    """, chroot_dir='foo')

    chroot_dir = posixpath.join(script.dirname, 'foo')

    os.makedirs(chroot_dir)
    with open(posixpath.join(chroot_dir, 'banana'), 'w') as f:
        f.write('pGh1XcBKCOwqDnNkyp43qK9Ixapnd4Kd')

    result = script.run()

    assert result.returncode == 0
    assert result.stderr == b'pGh1XcBKCOwqDnNkyp43qK9Ixapnd4Kd\n'


@pytest.mark.skipif(not psutil.LINUX, reason='only run on Linux')
@pytest.mark.sudo
def test_chrootdir_with_various_file_handling(pyscript):
    # FIXME: This scenario doesn't completely work as expected, but this
    # test is here just to make sure it doesn't completely fail.
    script = pyscript("""
        import os
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            sys.stdout.write('1hkCD5JwzzWzB2t5qnWg3FyZs8eaST8NYr4\\n')
            sys.stdout.flush()
            sys.stderr.write('2JQkKPfp6NFW5NmJiCKXeyJ4iCkHfwBs5Vp\\n')
            sys.stderr.flush()
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', pid_file='foo.pid',
                        detach=True, chroot_dir=os.getcwd(),
                        close_open_files=True, stdout_file='stdout.log',
                        stderr_file='stderr.log')
        daemon.do_action(sys.argv[1])
    """, chroot_dir='.')

    pid_file = posixpath.join(script.dirname, 'foo.pid')

    result = script.run('start')
    try:
        assert result.returncode == 0
        assert result.stdout == b'Starting foo ... OK\n'
        assert result.stderr == b''

        with open(pid_file, 'rb') as f:
            proc = psutil.Process(int(f.read()))

        assert proc.status() in {psutil.STATUS_RUNNING, psutil.STATUS_SLEEPING}

        with open(posixpath.join(script.dirname, 'stdout.log'), 'rb') as f:
            assert f.read() == b'1hkCD5JwzzWzB2t5qnWg3FyZs8eaST8NYr4\n'
        with open(posixpath.join(script.dirname, 'stderr.log'), 'rb') as f:
            assert f.read() == b'2JQkKPfp6NFW5NmJiCKXeyJ4iCkHfwBs5Vp\n'

        with pytest.raises(DaemonEnvironmentError) as exc_info:
            proc_get_open_fds(proc.pid)
        assert 'Unable to get open file descriptors' in str(exc_info.value)
    finally:
        result = script.run('stop')
        assert result.returncode == 0
        assert result.stdout == b'Stopping foo ... OK\n'
        assert result.stderr == b''


@pytest.mark.sudo
def test_chrootdir_detach_no_output_files(pyscript):
    script = pyscript("""
        import os
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', pid_file='foo.pid',
                        detach=True, chroot_dir=os.getcwd())
        daemon.do_action(sys.argv[1])
    """, chroot_dir='.')

    result = script.run('start')
    try:
        if psutil.LINUX:
            assert result.returncode == 0
            assert result.stdout == b'Starting foo ... OK\n'
            assert result.stderr == b''
        else:
            assert result.returncode == 1
            assert result.stdout == b'Starting foo ... FAILED\n'
            assert (b'The "/dev/null" device does not exist.'
                    in result.stderr)
            assert (b'ERROR: Child exited immediately with exit code'
                    in result.stderr)
    finally:
        result = script.run('stop')
        assert result.returncode == 0
        if psutil.LINUX:
            assert result.stdout == b'Stopping foo ... OK\n'
            assert result.stderr == b''
        else:
            assert result.stdout == b''
            assert result.stderr == b'WARNING: foo is not running\n'


def test_uid_and_gid_without_permission():
    nobody = getpwnam('nobody')
    daemon = Daemon(worker=lambda: None, uid=nobody.pw_uid, gid=nobody.pw_gid)
    with pytest.raises(DaemonError) as exc_info:
        daemon.do_action('start')
    assert ('Unable to setuid or setgid '
            '([Errno 1] Operation not permitted') in str(exc_info.value)


@pytest.mark.sudo
def test_uid_and_gid(pyscript):
    nobody = getpwnam('nobody')
    script = pyscript("""
        import os
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            time.sleep(10)

        daemon = Daemon(worker=worker, name='foo', pid_file='foo/foo.pid',
                        work_dir=os.getcwd(), uid={uid}, gid={gid})
        daemon.do_action(sys.argv[1])
    """.format(uid=nobody.pw_uid, gid=nobody.pw_gid))

    result = script.run('start')
    assert result.returncode == 0

    with open(posixpath.join(script.dirname, 'foo', 'foo.pid'), 'rb') as f:
        proc = psutil.Process(int(f.read()))

    uids = proc.uids()
    assert uids.real == uids.effective == uids.saved == nobody.pw_uid
    gids = proc.gids()
    assert gids.real == gids.effective == gids.saved == nobody.pw_gid

    script.run('stop')


def test_umask(pyscript):
    script = pyscript("""
        import os
        import sys
        import time
        from daemonocle import Daemon

        def worker():
            os.makedirs('foo')
            with open('foo/bar.txt', 'w') as f:
                f.write('hello world')
            time.sleep(10)

        kwargs = {'umask': int(sys.argv[2], 8)} if len(sys.argv) > 2 else {}
        daemon = Daemon(worker=worker, name='foo', pid_file='foo.pid',
                        work_dir=os.getcwd(), **kwargs)
        daemon.do_action(sys.argv[1])
    """)
    pid_file = posixpath.join(script.dirname, 'foo.pid')
    testdir = posixpath.join(script.dirname, 'foo')
    testfile = posixpath.join(testdir, 'bar.txt')

    result = script.run('start')
    assert result.returncode == 0
    assert os.stat(pid_file).st_mode & 0o777 == 0o644
    assert os.stat(testdir).st_mode & 0o777 == 0o755
    assert os.stat(testfile).st_mode & 0o777 == 0o644

    os.remove(testfile)
    os.rmdir(testdir)

    result = script.run('restart', '027')
    assert result.returncode == 0
    assert os.stat(pid_file).st_mode & 0o777 == 0o640
    assert os.stat(testdir).st_mode & 0o777 == 0o750
    assert os.stat(testfile).st_mode & 0o777 == 0o640

    os.remove(testfile)
    os.rmdir(testdir)

    result = script.run('restart', '077')
    assert result.returncode == 0
    assert os.stat(pid_file).st_mode & 0o777 == 0o600
    assert os.stat(testdir).st_mode & 0o777 == 0o700
    assert os.stat(testfile).st_mode & 0o777 == 0o600

    script.run('stop')


def test_is_detach_necessary_pid1(monkeypatch):
    def mock_os_getpid_1():
        return 1

    monkeypatch.setattr(os, 'getpid', mock_os_getpid_1)

    assert not Daemon._is_detach_necessary()


def test_is_detach_necessary_ppid1(monkeypatch):
    def mock_os_getppid_1():
        return 1

    monkeypatch.setattr(os, 'getppid', mock_os_getppid_1)

    # FIXME: This isn't really how I would prefer to test this,
    # but this is a difficult thing to test.
    assert Daemon._is_detach_necessary() == Daemon._is_in_container()
