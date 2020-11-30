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


PyScriptResult = namedtuple(
    'PyScriptResult', ['stdout', 'stderr', 'pid', 'returncode'])


class PyScript(object):

    def __init__(self, code, sudo=False, chrootdir=None):
        self.sudo = sudo
        self.dirname = self._make_temp_dir()
        self.basename = 'script.py'
        self.path = posixpath.join(self.dirname, self.basename)
        with open(self.path, 'wb') as f:
            f.write(textwrap.dedent(code.lstrip('\n')).encode('utf-8'))

        self.chrootdir = chrootdir
        if self.chrootdir is not None:
            self.chrootdir = posixpath.normpath(
                posixpath.join(self.dirname, self.chrootdir))

    def _make_temp_dir(self):
        if self.sudo and sys.platform == 'darwin':
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

    def run(self, *args):
        subenv = os.environ.copy()
        subenv['PYTHONUNBUFFERED'] = 'x'

        if self.chrootdir is not None:
            # The chroot messes up coverage
            cov_core_datafile = subenv.get('COV_CORE_DATAFILE')
            if cov_core_datafile:
                cov_file_name = posixpath.basename(cov_core_datafile)
                cov_file_dir = posixpath.join(
                    self.chrootdir, self.dirname.lstrip('/'))
                if not posixpath.isdir(cov_file_dir):
                    os.makedirs(cov_file_dir)
                subenv['COV_CORE_DATAFILE'] = posixpath.join(
                    self.dirname, cov_file_name)

        base_command = [sys.executable, self.path]
        if self.sudo:
            base_command = ['sudo', '-E'] + base_command

        proc = subprocess.Popen(
            base_command + list(args), cwd=self.dirname, env=subenv,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()

        return PyScriptResult(stdout, stderr, proc.pid, proc.returncode)

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
        for dirpath, dirnames, filenames in os.walk(self.dirname):
            for filename in filenames:
                if not _re_coverage_filename.match(filename):
                    continue
                coverage_files.append(posixpath.join(dirpath, filename))

        for coverage_file in coverage_files:
            shutil.move(coverage_file, BASE_DIR)

        shutil.rmtree(self.dirname)


@pytest.fixture(scope='function')
def pyscript(request):
    pfs = []

    needs_sudo = request.node.get_closest_marker('sudo') is not None

    def factory(code, chrootdir=None):
        pf = PyScript(code, sudo=needs_sudo, chrootdir=chrootdir)
        pfs.append(pf)
        return pf

    def teardown():
        for pf in pfs:
            pf.teardown()

    request.addfinalizer(teardown)

    return factory
