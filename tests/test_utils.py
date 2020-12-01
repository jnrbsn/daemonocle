import errno
import os
import posixpath
import subprocess

import pytest

from daemonocle._utils import check_dir_exists, proc_get_open_fds
from daemonocle.exceptions import DaemonEnvironmentError


def test_check_dir_exists(temp_dir):
    test_dir = posixpath.join(temp_dir, 'foo')
    os.mkdir(test_dir)
    check_dir_exists(test_dir)

    with pytest.raises(OSError) as exc_info:
        check_dir_exists(posixpath.join(temp_dir, 'baz'))
    assert exc_info.value.errno == errno.ENOENT
    assert 'No such file or directory' in str(exc_info.value)

    test_file = posixpath.join(temp_dir, 'bar')
    with open(test_file, 'w') as f:
        f.write('bar\n')
    with pytest.raises(OSError) as exc_info:
        check_dir_exists(test_file)
    assert exc_info.value.errno == errno.ENOTDIR
    assert 'Not a directory' in str(exc_info.value)


def test_proc_get_open_fds_fallbacks_current_proc(temp_dir, monkeypatch):
    # Normal
    result_1 = proc_get_open_fds()

    def mock_os_listdir_scandir(path='.'):
        raise OSError(errno.ENOENT, 'No such file or directory', path)

    monkeypatch.setattr(os, 'listdir', mock_os_listdir_scandir)
    if hasattr(os, 'scandir'):
        monkeypatch.setattr(os, 'scandir', mock_os_listdir_scandir)

    # Simulating not being able to read "/proc/<pid>/fd"
    result_2 = proc_get_open_fds()

    temp_lsof = posixpath.join(temp_dir, 'lsof')
    with open(temp_lsof, 'w') as f:
        f.write('#!/bin/sh\nexit 42\n')
    os.chmod(temp_lsof, 0o755)

    orig_env_path = os.environ.get('PATH', '')
    temp_env_path = (
        ':'.join((temp_dir, orig_env_path)) if orig_env_path else temp_dir)
    try:
        os.environ['PATH'] = temp_env_path

        # Simulating "lsof" error
        result_3 = proc_get_open_fds()
    finally:
        os.environ['PATH'] = orig_env_path

    assert result_1 == result_2 == result_3


def test_proc_get_open_fds_fallbacks_other_proc(temp_dir, monkeypatch):
    proc = subprocess.Popen(['sleep', '60'])
    pid = proc.pid
    try:
        # Normal
        result_1 = proc_get_open_fds(pid)

        def mock_os_listdir_scandir(path='.'):
            raise OSError(errno.ENOENT, 'No such file or directory', path)

        monkeypatch.setattr(os, 'listdir', mock_os_listdir_scandir)
        if hasattr(os, 'scandir'):
            monkeypatch.setattr(os, 'scandir', mock_os_listdir_scandir)

        # Simulating not being able to read "/proc/<pid>/fd"
        result_2 = proc_get_open_fds(pid)

        assert result_1 == result_2

        temp_lsof = posixpath.join(temp_dir, 'lsof')
        with open(temp_lsof, 'w') as f:
            f.write('#!/bin/sh\nexit 42\n')
        os.chmod(temp_lsof, 0o755)

        orig_env_path = os.environ.get('PATH', '')
        temp_env_path = (
            ':'.join((temp_dir, orig_env_path)) if orig_env_path else temp_dir)
        os.environ['PATH'] = temp_env_path
        try:
            # Simulating "lsof" error
            with pytest.raises(DaemonEnvironmentError) as exc_info:
                proc_get_open_fds(pid)
            assert 'Unable to get open file descriptors' in str(exc_info.value)
        finally:
            os.environ['PATH'] = orig_env_path
    finally:
        proc.terminate()
        proc.wait()
