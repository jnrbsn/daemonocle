from collections import namedtuple
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

import psutil
import pytest


def pytest_runtest_setup(item):
    sudo_marker = item.get_marker('sudo')
    if sudo_marker is not None:
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
        self.dirname = os.path.realpath(
            tempfile.mkdtemp(prefix='daemonocle_pytest_'))
        # This chmod is necessary for the setuid/setgid tests
        os.chmod(self.dirname, 0o711)
        self.basename = 'script.py'
        self.realpath = os.path.join(self.dirname, self.basename)
        with open(self.realpath, 'wb') as f:
            f.write(textwrap.dedent(code.lstrip('\n')).encode('utf-8'))
        self.sudo = sudo

    def run(self, *args):
        subenv = os.environ.copy()
        subenv['PYTHONUNBUFFERED'] = 'x'
        base_command = [sys.executable, self.realpath]
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
                        self.realpath in proc.cmdline()):
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

    def factory(code):
        pf = PyScript(code, sudo=hasattr(request.function, 'sudo'))
        pfs.append(pf)
        return pf

    def teardown():
        for pf in pfs:
            pf.teardown()

    request.addfinalizer(teardown)

    return factory
