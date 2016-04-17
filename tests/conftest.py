from collections import namedtuple
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

import psutil
import pytest


PyScriptResult = namedtuple(
    'PyScriptResult', ['stdout', 'stderr', 'pid', 'returncode'])


class PyScript(object):

    def __init__(self, code):
        self.dirname = os.path.realpath(
            tempfile.mkdtemp(prefix='daemonocle_pytest_'))
        self.basename = 'script.py'
        self.realpath = os.path.join(self.dirname, self.basename)
        with open(self.realpath, 'wb') as f:
            f.write(textwrap.dedent(code.lstrip('\n')).encode('utf-8'))

    def run(self, *args):
        subenv = os.environ.copy()
        subenv['PYTHONUNBUFFERED'] = 'x'
        proc = subprocess.Popen(
            [sys.executable, self.realpath] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.dirname,
            env=subenv)
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
        gone, alive = psutil.wait_procs(procs, timeout=1)
        if alive:
            raise OSError('Failed to terminate subprocesses')
        shutil.rmtree(self.dirname)


@pytest.fixture(scope='function')
def pyscript(request):
    pfs = []

    def factory(code):
        pf = PyScript(code)
        pfs.append(pf)
        return pf

    def teardown():
        for pf in pfs:
            pf.teardown()

    request.addfinalizer(teardown)

    return factory
