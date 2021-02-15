import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from collections import namedtuple

import psutil
import pytest

BASE_DIR = posixpath.realpath(posixpath.dirname(posixpath.dirname(__file__)))

_re_coverage_filename = re.compile(r'^\.coverage(\..+)?$')


def pytest_runtest_setup(item):
    needs_sudo = item.get_closest_marker('sudo') is not None
    if needs_sudo:
        try:
            with open(os.devnull, 'w') as devnull:
                subprocess.check_call(
                    ['sudo', '-n', 'true'], stdout=devnull, stderr=devnull)
        except subprocess.CalledProcessError:
            pytest.skip('must be able to run sudo without a password')


def _make_temp_dir(needs_sudo=False):
    if needs_sudo and psutil.MACOS:
        # macOS has user-specific TMPDIRs, which don't work well
        # with tests that require changing users. So this gets a
        # global multi-user TMPDIR by using sudo.
        base_temp_dir = subprocess.check_output([
            'sudo', sys.executable, '-c',
            'import tempfile as t; print(t.gettempdir())',
        ]).decode('utf-8').strip()
    else:
        base_temp_dir = tempfile.gettempdir()

    temp_dir = posixpath.realpath(
        tempfile.mkdtemp(prefix='daemonocle_pytest_', dir=base_temp_dir))
    # This chmod is necessary for the setuid/setgid tests
    os.chmod(temp_dir, 0o711)

    return temp_dir


@pytest.fixture(scope='function')
def temp_dir(request):
    needs_sudo = request.node.get_closest_marker('sudo') is not None

    path = _make_temp_dir(needs_sudo=needs_sudo)

    def teardown():
        shutil.rmtree(path)

    request.addfinalizer(teardown)

    return path


PyScriptResult = namedtuple(
    'PyScriptResult', ['stdout', 'stderr', 'pid', 'returncode'])


class PyScript(object):

    def __init__(self, code, sudo=False, chroot_dir=None):
        self.sudo = sudo
        self.dirname = _make_temp_dir(needs_sudo=sudo)
        self.basename = 'script.py'
        self.path = posixpath.join(self.dirname, self.basename)
        with open(self.path, 'wb') as f:
            f.write(textwrap.dedent(code.lstrip('\n')).encode('utf-8'))

        self.chroot_dir = chroot_dir
        if self.chroot_dir is not None:
            self.chroot_dir = posixpath.normpath(
                posixpath.join(self.dirname, self.chroot_dir))

        self.process = None

    def _setup_chroot_dir(self):
        setup_script = PyScript("""
            import os
            import posixpath
            import stat
            import sys

            chroot_dir = sys.argv[1]
            dev_dir = posixpath.join(chroot_dir, 'dev')
            if not posixpath.isdir(dev_dir):
                os.makedirs(dev_dir, 0o755)

            devices = [
                ('null', (1, 3)),
                ('zero', (1, 5)),
                ('random', (1, 8)),
                ('urandom', (1, 9)),
            ]

            for name, device_nums in devices:
                device_path = posixpath.join(dev_dir, name)
                if posixpath.exists(device_path):
                    continue
                os.mknod(
                    device_path,
                    stat.S_IFCHR | 0o666,
                    os.makedev(*device_nums),
                )
        """, sudo=True)
        result = setup_script.run(self.chroot_dir)
        assert result.returncode == 0

    def start(self, *args):
        if self.process is not None:
            raise RuntimeError(
                'Process already started (PID {})'.format(self.process.pid))

        subenv = os.environ.copy()
        subenv['PYTHONUNBUFFERED'] = 'x'

        if self.chroot_dir is not None:
            # The chroot messes up coverage
            cov_core_datafile = subenv.get('COV_CORE_DATAFILE')
            if cov_core_datafile:
                cov_file_name = posixpath.basename(cov_core_datafile)
                cov_file_dir = posixpath.join(
                    self.chroot_dir, self.dirname.lstrip('/'))
                if not posixpath.isdir(cov_file_dir):
                    os.makedirs(cov_file_dir)
                subenv['COV_CORE_DATAFILE'] = posixpath.join(
                    self.dirname, cov_file_name)

            if self.sudo and psutil.LINUX:
                self._setup_chroot_dir()

        base_command = [sys.executable, self.path]
        if self.sudo:
            base_command = ['sudo', '-E'] + base_command

        self.process = subprocess.Popen(
            base_command + list(args), cwd=self.dirname, env=subenv,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        return self.process

    def join(self):
        stdout, stderr = self.process.communicate()
        result = PyScriptResult(
            stdout, stderr, self.process.pid, self.process.returncode)
        self.process = None
        return result

    def run(self, *args):
        self.start(*args)
        return self.join()

    def teardown(self):
        procs = []
        for proc in psutil.process_iter():
            try:
                if (proc.exe() == sys.executable and
                        self.path in proc.cmdline()):
                    proc.terminate()
                    procs.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        if psutil.wait_procs(procs, timeout=1)[1]:
            raise OSError('Failed to terminate subprocesses')

        coverage_files = []
        for dirpath, _, filenames in os.walk(self.dirname):
            for filename in filenames:
                if not _re_coverage_filename.match(filename):
                    continue
                coverage_files.append(posixpath.join(dirpath, filename))

        for coverage_file in coverage_files:
            shutil.move(coverage_file, BASE_DIR)

        if self.chroot_dir and self.sudo and psutil.LINUX:
            chroot_dev_dir = posixpath.join(self.chroot_dir, 'dev')
            assert chroot_dev_dir != '/dev'  # Safety check
            if posixpath.exists(chroot_dev_dir):
                subprocess.check_call(['sudo', 'rm', '-rf', chroot_dev_dir])

        shutil.rmtree(self.dirname)


@pytest.fixture(scope='function')
def pyscript(request):
    pfs = []

    needs_sudo = request.node.get_closest_marker('sudo') is not None

    def factory(code, chroot_dir=None):
        pf = PyScript(code, sudo=needs_sudo, chroot_dir=chroot_dir)
        pfs.append(pf)
        return pf

    def teardown():
        for pf in pfs:
            pf.teardown()

    request.addfinalizer(teardown)

    return factory
