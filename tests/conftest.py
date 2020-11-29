import os
import posixpath
import shutil
import subprocess
import sys
import tempfile
import textwrap
from collections import namedtuple

import psutil
import pytest


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

    def __init__(self, code, sudo=False):
        self.sudo = sudo
        self.dirname = self._make_temp_dir()
        self.basename = 'script.py'
        self.path = posixpath.join(self.dirname, self.basename)
        with open(self.path, 'wb') as f:
            f.write(textwrap.dedent(code.lstrip('\n')).encode('utf-8'))

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

        temp_dir = posixpath.abspath(
            tempfile.mkdtemp(prefix='daemonocle_pytest_', dir=base_temp_dir))
        # This chmod is necessary for the setuid/setgid tests
        os.chmod(temp_dir, 0o711)

        return temp_dir

    def run(self, *args):
        subenv = os.environ.copy()
        subenv['PYTHONUNBUFFERED'] = 'x'
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
        shutil.rmtree(self.dirname)


@pytest.fixture(scope='function')
def pyscript(request):
    pfs = []

    needs_sudo = request.node.get_closest_marker('sudo') is not None

    def factory(code):
        pf = PyScript(code, sudo=needs_sudo)
        pfs.append(pf)
        return pf

    def teardown():
        for pf in pfs:
            pf.teardown()

    request.addfinalizer(teardown)

    return factory
