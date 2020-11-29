import os
import posixpath
import shutil
from glob import glob
from pwd import getpwnam

import psutil
import pytest

from daemonocle import Daemon, DaemonError
from daemonocle.utils import proc_get_open_fds


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
        daemon = Daemon(worker=worker, prog='foo', pidfile='foo.pid',
                        workdir=os.getcwd(),
                        close_open_files=close_files)
        daemon.do_action(sys.argv[1])
    """)
    pidfile = posixpath.join(script.dirname, 'foo.pid')

    script.run('start', '0')

    with open(pidfile, 'rb') as f:
        proc = psutil.Process(int(f.read()))

    assert len(proc_get_open_fds(proc)) >= 5
    open_files = {posixpath.relpath(x.path, script.dirname)
                  for x in proc.open_files()}
    assert open_files == {'foo.txt', 'foo.pid'}

    script.run('restart', '1')

    with open(pidfile, 'rb') as f:
        proc = psutil.Process(int(f.read()))

    assert len(proc_get_open_fds(proc)) == 4
    open_files = {posixpath.relpath(x.path, script.dirname)
                  for x in proc.open_files()}
    assert open_files == {'foo.pid'}

    script.run('stop')


def test_chrootdir_without_permission():
    daemon = Daemon(worker=lambda: None, chrootdir=os.getcwd())
    with pytest.raises(DaemonError) as excinfo:
        daemon.do_action('start')
    assert ('Unable to change root directory '
            '([Errno 1] Operation not permitted') in str(excinfo.value)


@pytest.mark.sudo
def test_chrootdir(pyscript):
    script = pyscript("""
        import os
        import sys
        from daemonocle import Daemon

        def worker():
            with open('/banana', 'r') as f:
                sys.stderr.write(f.read() + '\\n')

        daemon = Daemon(worker=worker, prog='foo', detach=False,
                        chrootdir=os.path.join(os.getcwd(), 'foo'))
        daemon.do_action('start')
    """)

    chrootdir = posixpath.join(script.dirname, 'foo')
    os.makedirs(chrootdir)
    with open(posixpath.join(chrootdir, 'banana'), 'w') as f:
        f.write('pGh1XcBKCOwqDnNkyp43qK9Ixapnd4Kd')

    # The chroot messes up coverage
    cov_core_datafile = os.environ.get('COV_CORE_DATAFILE')
    if cov_core_datafile:
        cov_file_name = posixpath.basename(cov_core_datafile)
        cov_file_dir = posixpath.join(chrootdir, script.dirname.lstrip(os.sep))
        os.makedirs(cov_file_dir)
        os.environ['COV_CORE_DATAFILE'] = posixpath.join(
            script.dirname, cov_file_name)

    result = script.run()

    # Move coverage files to expected location
    if cov_core_datafile:
        for cov_file in glob(
                posixpath.join(cov_file_dir, cov_file_name + '*')):
            shutil.move(cov_file, script.dirname)
        os.environ['COV_CORE_DATAFILE'] = cov_core_datafile

    assert result.returncode == 0
    assert result.stderr == b'pGh1XcBKCOwqDnNkyp43qK9Ixapnd4Kd\n'


def test_uid_and_gid_without_permission():
    nobody = getpwnam('nobody')
    daemon = Daemon(worker=lambda: None, uid=nobody.pw_uid, gid=nobody.pw_gid)
    with pytest.raises(DaemonError) as excinfo:
        daemon.do_action('start')
    assert ('Unable to setuid or setgid '
            '([Errno 1] Operation not permitted') in str(excinfo.value)


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

        daemon = Daemon(worker=worker, prog='foo', pidfile='foo/foo.pid',
                        workdir=os.getcwd(), uid={uid}, gid={gid})
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
        daemon = Daemon(worker=worker, prog='foo', pidfile='foo.pid',
                        workdir=os.getcwd(), **kwargs)
        daemon.do_action(sys.argv[1])
    """)
    pidfile = posixpath.join(script.dirname, 'foo.pid')
    testdir = posixpath.join(script.dirname, 'foo')
    testfile = posixpath.join(testdir, 'bar.txt')

    result = script.run('start')
    assert result.returncode == 0
    assert os.stat(pidfile).st_mode & 0o777 == 0o644
    assert os.stat(testdir).st_mode & 0o777 == 0o755
    assert os.stat(testfile).st_mode & 0o777 == 0o644

    os.remove(testfile)
    os.rmdir(testdir)

    result = script.run('restart', '027')
    assert result.returncode == 0
    assert os.stat(pidfile).st_mode & 0o777 == 0o640
    assert os.stat(testdir).st_mode & 0o777 == 0o750
    assert os.stat(testfile).st_mode & 0o777 == 0o640

    os.remove(testfile)
    os.rmdir(testdir)

    result = script.run('restart', '077')
    assert result.returncode == 0
    assert os.stat(pidfile).st_mode & 0o777 == 0o600
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
